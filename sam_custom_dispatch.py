"""
SAM Custom Dispatch Module: Economically Optimal Battery Dispatch

This module implements custom dispatch schedules for SAM's Custom Dispatch mode (mode 3)
to maximize battery utilization based on Time-of-Use electricity rates.

Key Features:
- Economic optimization based on utility rates
- Rate-based scheduling using TOU electricity rates
- Battery degradation cost considerations
- Integration with SAM PySAM models

Usage:
    from sam_custom_dispatch import CustomDispatchScheduleGenerator
    from electricity_rate_helpers import PGE_RATE_PLANS
    
    generator = CustomDispatchScheduleGenerator(PGE_RATE_PLANS['E-TOU-C'])
    charge_sched, discharge_sched, gridcharge_sched = generator.generate_custom_dispatch_schedule(
        load_profile, solar_profile
    )
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import os
import sys
import json

# SAM Python API
import PySAM.Pvwattsv8 as pvwatts
import PySAM.Battwatts as battery_model
import PySAM.ResourceTools as tools

# Add helpers to path
sys.path.append('helpers')
from electricity_rate_helpers import PGE_RATE_PLANS


class CustomDispatchScheduleGenerator:
    """
    Generate SAM custom dispatch schedules based on utility rates and economic optimization
    """
    
    def __init__(self, rate_plan, battery_capacity_kwh=13.5, cycle_cost_per_kwh=0.185):
        self.rate_plan = rate_plan
        self.battery_capacity = battery_capacity_kwh
        self.cycle_cost = cycle_cost_per_kwh
        self.min_soc = 10.0  # Minimum SOC (%)
        self.max_soc = 95.0  # Maximum SOC (%) - Tesla Powerwall practical max
        
    def get_hourly_rates(self, year=2018):
        """Generate 8760 hourly electricity rates for the year"""
        rates = []
        start_date = datetime(year, 1, 1)
        
        for hour in range(8760):
            timestamp = start_date + timedelta(hours=hour)
            rate = self._get_rate_for_hour(timestamp)
            rates.append(rate)
            
        return rates
    
    def _get_rate_for_hour(self, timestamp):
        """Get electricity rate for specific hour"""
        month = timestamp.month
        hour = timestamp.hour
        weekday = timestamp.weekday() < 5  # Monday=0, Sunday=6
        
        # Determine season (PG&E: Summer = May-Oct, Winter = Nov-Apr)
        is_summer = month in [5, 6, 7, 8, 9, 10]
        season = 'summer' if is_summer else 'winter'
        
        # Use weekday rates (weekend rates could be added later)
        rates = self.rate_plan[season]['weekdays']
        
        # Check if peak hours (4 PM - 9 PM)
        if hour in rates['peakHours']:
            return rates['peak']
        else:
            return rates['offPeak']
    
    def generate_custom_dispatch_schedule(self, load_profile, solar_profile):
        """
        Generate SAM custom dispatch schedule arrays using peak-hour optimization logic
        
        Strategy:
        1) Look ahead to calculate daily peak load (4-9pm)
        2) Prioritize solar for charging battery up to peak load requirement
        3) Use remaining solar for household load, then top up battery
        4) Discharge battery during 4-9pm peak hours (80% max, 20% min SOC)
        
        Returns: (charge_schedule, discharge_schedule, gridcharge_schedule)
        """
        hours = len(load_profile)
        hourly_rates = self.get_hourly_rates()
        
        # Initialize dispatch arrays (0 = no action, values 0-1 represent fraction of max power)
        charge_schedule = np.zeros(hours)      # Battery charging from excess solar
        discharge_schedule = np.zeros(hours)   # Battery discharging to load
        gridcharge_schedule = np.zeros(hours)  # Battery charging from grid
        
        # Battery simulation parameters
        current_soc = 50.0  # Start at 50% SOC
        battery_kwh = current_soc / 100 * self.battery_capacity
        max_charge_power = 5.0  # kW
        max_discharge_power = 5.0  # kW
        
        # Operating SOC limits for peak hour strategy
        peak_max_soc = 90.0  # Don't discharge below this during peak
        peak_min_soc = 20.0  # Don't charge above this for peak preparation
        
        # Track hourly decisions for analysis
        dispatch_log = []
        
        # Track daily predictions for logging
        daily_predictions = {}
        
        # Process each hour
        for h in range(hours):
            load = load_profile[h]
            solar = solar_profile[h] if solar_profile else 0
            rate = hourly_rates[h]
            hour_of_day = h % 24
            
            # Determine if we're in peak hours (4 PM - 9 PM)
            is_peak_hour = 16 <= hour_of_day <= 20  # 4 PM to 8 PM (inclusive)
            
            # Look ahead to calculate today's peak load requirement
            day_start = (h // 24) * 24
            day_end = min(day_start + 24, hours)
            peak_start_today = day_start + 16  # 4 PM
            peak_end_today = min(day_start + 21, hours)  # 9 PM
            current_day = h // 24
            
            # Calculate total peak load for today
            if peak_end_today > peak_start_today:
                today_peak_load = sum(load_profile[peak_start_today:peak_end_today])
            else:
                today_peak_load = 0
            
            # Calculate energy needed from battery for today's peak
            # (This is the target we want to have stored)
            peak_battery_target_kwh = min(today_peak_load, 
                                        (peak_max_soc - peak_min_soc) / 100 * self.battery_capacity)
            
            # Log daily predictions (only once per day at 6 AM)
            if hour_of_day == 6 and current_day not in daily_predictions:
                battery_available_for_peak = max(0, battery_kwh - (peak_min_soc / 100 * self.battery_capacity))
                
                daily_predictions[current_day] = {
                    'day': current_day,
                    'peak_load_kwh': today_peak_load,
                    'peak_target_kwh': peak_battery_target_kwh,
                    'battery_ready_kwh': battery_available_for_peak,
                    'current_soc': current_soc,
                    'battery_total_kwh': battery_kwh
                }
                
                print(f"\n📊 Day {current_day + 1} Peak Prediction (6 AM):")
                print(f"  Peak load (4-9 PM): {today_peak_load:.2f} kWh")
                print(f"  Battery target: {peak_battery_target_kwh:.2f} kWh")
                print(f"  Current battery SOC: {current_soc:.1f}% ({battery_kwh:.2f} kWh)")
                print(f"  Available for peak: {battery_available_for_peak:.2f} kWh")
                
                coverage_pct = (battery_available_for_peak / today_peak_load * 100) if today_peak_load > 0 else 0
                print(f"  Expected peak coverage: {coverage_pct:.1f}%")
                
                if battery_available_for_peak < peak_battery_target_kwh:
                    shortfall = peak_battery_target_kwh - battery_available_for_peak
                    print(f"  ⚠️ Battery shortfall: {shortfall:.2f} kWh (need to charge more)")
                else:
                    surplus = battery_available_for_peak - peak_battery_target_kwh
                    print(f"  ✅ Battery surplus: {surplus:.2f} kWh (well prepared)")
            
            # Additional logging when entering peak hours
            if hour_of_day == 16 and h > 0:  # 4 PM - start of peak
                battery_available_for_peak = max(0, battery_kwh - (peak_min_soc / 100 * self.battery_capacity))
                print(f"\n🔋 Peak Hour Start (4 PM) - Day {current_day + 1}:")
                print(f"  Battery SOC: {current_soc:.1f}% ({battery_kwh:.2f} kWh)")
                print(f"  Available for peak: {battery_available_for_peak:.2f} kWh")
                print(f"  Peak load target: {today_peak_load:.2f} kWh")
                
                final_coverage = (battery_available_for_peak / today_peak_load * 100) if today_peak_load > 0 else 0
                print(f"  Final peak coverage: {final_coverage:.1f}%")
            
            # Decision variables
            charge_action = 0.0
            discharge_action = 0.0
            gridcharge_action = 0.0
            
            if is_peak_hour:
                # PEAK HOURS (4-9 PM): Discharge battery to meet load
                if current_soc > peak_min_soc and load > 0:
                    battery_available = battery_kwh - (peak_min_soc / 100 * self.battery_capacity)
                    
                    if battery_available > 0:
                        # Discharge to meet as much load as possible
                        discharge_amount = min(load, battery_available, max_discharge_power)
                        discharge_action = discharge_amount / max_discharge_power
                        
                        # Predict new SOC after discharge
                        new_battery_kwh = battery_kwh - discharge_amount
                        new_soc = (new_battery_kwh / self.battery_capacity) * 100
                        
                        # Debug logging for SOC violations
                        if new_soc < peak_min_soc:
                            print(f"⚠️ SOC VIOLATION DETECTED at hour {h} (Day {h//24 + 1}, {hour_of_day}:00)")
                            print(f"  Current SOC: {current_soc:.1f}% ({battery_kwh:.2f} kWh)")
                            print(f"  Attempted discharge: {discharge_amount:.2f} kWh")
                            print(f"  Predicted new SOC: {new_soc:.1f}% ({new_battery_kwh:.2f} kWh)")
                            print(f"  Min SOC limit: {peak_min_soc:.1f}%")
                            print(f"  Load: {load:.2f} kW")
                            print(f"  Battery available: {battery_available:.2f} kWh")
                            
                            # Adjust discharge to respect SOC limit
                            safe_discharge = battery_kwh - (peak_min_soc / 100 * self.battery_capacity)
                            discharge_amount = max(0, safe_discharge)
                            discharge_action = discharge_amount / max_discharge_power if max_discharge_power > 0 else 0
                            print(f"  Adjusted discharge: {discharge_amount:.2f} kWh")
                        
                        battery_kwh -= discharge_amount
                        current_soc = (battery_kwh / self.battery_capacity) * 100
                        
                        # Final SOC check
                        if current_soc < peak_min_soc - 0.1:  # Small tolerance for floating point
                            print(f"🚨 CRITICAL: SOC still below limit after adjustment!")
                            print(f"  Final SOC: {current_soc:.2f}%")
                            print(f"  Limit: {peak_min_soc:.1f}%")
            
            else:
                # NON-PEAK HOURS: Implement solar prioritization strategy
                if solar > 0:
                    # Calculate how much battery capacity we need for peak preparation
                    current_battery_energy = battery_kwh
                    peak_prep_target = peak_battery_target_kwh + (peak_min_soc / 100 * self.battery_capacity)
                    peak_prep_needed = max(0, peak_prep_target - current_battery_energy)
                    
                    # 1. First Priority: Charge battery for peak hours
                    if peak_prep_needed > 0 and current_soc < peak_max_soc:
                        battery_capacity_available = min(
                            (peak_max_soc - current_soc) / 100 * self.battery_capacity,
                            peak_prep_needed
                        )
                        
                        # Debug charging logic
                        if h < 100 or (h % 1000 == 0):  # Debug first 100 hours and every 1000th hour
                            print(f"🔋 CHARGING DEBUG at hour {h} (Day {h//24 + 1}, {hour_of_day}:00)")
                            print(f"  Current SOC: {current_soc:.1f}% ({battery_kwh:.2f} kWh)")
                            print(f"  Solar available: {solar:.2f} kW")
                            print(f"  Peak prep needed: {peak_prep_needed:.2f} kWh")
                            print(f"  Peak max SOC limit: {peak_max_soc:.1f}%")
                            print(f"  Battery capacity available: {battery_capacity_available:.2f} kWh")
                        
                        if battery_capacity_available > 0:
                            charge_amount = min(solar, battery_capacity_available, max_charge_power)
                            charge_action = charge_amount / max_charge_power
                            
                            old_soc = current_soc
                            battery_kwh += charge_amount
                            current_soc = (battery_kwh / self.battery_capacity) * 100
                            solar -= charge_amount  # Reduce available solar
                            
                            # Debug successful charging
                            if h < 100 or (h % 1000 == 0):
                                print(f"  ✅ CHARGED: {charge_amount:.2f} kWh")
                                print(f"  SOC: {old_soc:.1f}% → {current_soc:.1f}%")
                                print(f"  Remaining solar: {solar:.2f} kW")
                        else:
                            if h < 100 or (h % 1000 == 0):
                                print(f"  ❌ NO CHARGING: battery_capacity_available = 0")
                    else:
                        if h < 100 or (h % 1000 == 0) and solar > 0:
                            print(f"🚫 CHARGING BLOCKED at hour {h}")
                            print(f"  Peak prep needed: {peak_prep_needed:.2f} kWh")
                            print(f"  Current SOC: {current_soc:.1f}%")
                            print(f"  Peak max SOC: {peak_max_soc:.1f}%")
                            print(f"  Solar available: {solar:.2f} kW")
                    
                    # 2. Second Priority: Meet household load with remaining solar
                    if solar > 0 and load > 0:
                        load_met_by_solar = min(solar, load)
                        solar -= load_met_by_solar  # Reduce available solar
                        # Note: This doesn't require a dispatch action in SAM as it's automatic
                    
                    # 3. Third Priority: Top up battery with any remaining solar
                    if solar > 0 and current_soc < self.max_soc:
                        battery_capacity_available = (self.max_soc - current_soc) / 100 * self.battery_capacity
                        
                        if h < 100 or (h % 1000 == 0):
                            print(f"🔋 TOP-UP DEBUG at hour {h}")
                            print(f"  Remaining solar: {solar:.2f} kW")
                            print(f"  Current SOC: {current_soc:.1f}%")
                            print(f"  Max SOC limit: {self.max_soc:.1f}%")
                            print(f"  Battery capacity available for top-up: {battery_capacity_available:.2f} kWh")
                            print(f"  Current charge action: {charge_action:.3f}")
                        
                        if battery_capacity_available > 0:
                            additional_charge = min(solar, battery_capacity_available, max_charge_power - charge_action * max_charge_power)
                            
                            if h < 100 or (h % 1000 == 0):
                                print(f"  Additional charge calculated: {additional_charge:.2f} kWh")
                                print(f"  Max charge power remaining: {max_charge_power - charge_action * max_charge_power:.2f} kW")
                            
                            if additional_charge > 0:
                                # Add to existing charge action
                                old_soc = current_soc
                                total_charge = charge_action * max_charge_power + additional_charge
                                charge_action = min(total_charge / max_charge_power, 1.0)
                                battery_kwh += additional_charge
                                current_soc = (battery_kwh / self.battery_capacity) * 100
                                
                                if h < 100 or (h % 1000 == 0):
                                    print(f"  ✅ TOP-UP CHARGED: {additional_charge:.2f} kWh")
                                    print(f"  SOC: {old_soc:.1f}% → {current_soc:.1f}%")
                                    print(f"  Total charge action: {charge_action:.3f}")
                            else:
                                if h < 100 or (h % 1000 == 0):
                                    print(f"  ❌ NO TOP-UP: additional_charge = 0")
                        else:
                            if h < 100 or (h % 1000 == 0):
                                print(f"  ❌ NO TOP-UP: battery_capacity_available = 0")
                    else:
                        if h < 100 or (h % 1000 == 0) and solar > 0:
                            print(f"🚫 TOP-UP BLOCKED at hour {h}")
                            print(f"  Solar: {solar:.2f} kW")
                            print(f"  Current SOC: {current_soc:.1f}%")
                            print(f"  Max SOC: {self.max_soc:.1f}%")
                
                # Handle any remaining load not met by solar (use grid)
                # This is automatic in SAM, no dispatch action needed
            
            # Store dispatch decisions
            charge_schedule[h] = charge_action
            discharge_schedule[h] = discharge_action
            gridcharge_schedule[h] = gridcharge_action
            
            # Debug: Track SOC violations throughout simulation
            if current_soc < 15.0:  # Below safe operating range
                print(f"🔴 LOW SOC WARNING at hour {h} (Day {h//24 + 1}, {hour_of_day}:00)")
                print(f"  SOC: {current_soc:.2f}% ({battery_kwh:.2f} kWh)")
                print(f"  Is peak hour: {is_peak_hour}")
                print(f"  Actions: charge={charge_action:.3f}, discharge={discharge_action:.3f}")
                print(f"  Load: {load:.2f} kW, Solar: {solar:.2f} kW")
                
                if current_soc < 10.0:
                    print(f"🚨 CRITICAL SOC at hour {h}: {current_soc:.2f}%")
            
            # Log for analysis
            dispatch_log.append({
                'hour': h,
                'hour_of_day': hour_of_day,
                'rate': rate,
                'soc': current_soc,
                'load': load,
                'solar': solar_profile[h] if solar_profile else 0,
                'is_peak': is_peak_hour,
                'peak_load_target': today_peak_load,
                'charge': charge_action,
                'discharge': discharge_action,
                'gridcharge': gridcharge_action
            })
        
        self.dispatch_log = pd.DataFrame(dispatch_log)
        
        # Debug: Print algorithm parameters and initial diagnosis
        print(f"\n🔍 ALGORITHM PARAMETERS DEBUG:")
        print("=" * 50)
        print(f"Battery capacity: {self.battery_capacity:.1f} kWh")
        print(f"Starting SOC: 50.0%")
        print(f"Peak operating range: {peak_min_soc:.1f}% - {peak_max_soc:.1f}%")
        print(f"Max SOC limit: {self.max_soc:.1f}%")
        print(f"Max charge power: {max_charge_power:.1f} kW")
        print(f"Max discharge power: {max_discharge_power:.1f} kW")
        
        # Analyze why SOC might be limited
        soc_values = [log['soc'] for log in dispatch_log]
        max_soc_reached = max(soc_values)
        charge_events = sum(1 for log in dispatch_log if log['charge'] > 0)
        
        print(f"\nSOC ANALYSIS:")
        print(f"Maximum SOC reached: {max_soc_reached:.1f}%")
        print(f"Total charging events: {charge_events}")
        
        if max_soc_reached < 60:
            print(f"🚨 SOC ISSUE DETECTED: Battery never exceeded {max_soc_reached:.1f}%")
            
            # Check for common issues
            total_solar = sum(log['solar'] for log in dispatch_log)
            total_load = sum(log['load'] for log in dispatch_log)
            
            print(f"Total annual solar: {total_solar:.0f} kWh")
            print(f"Total annual load: {total_load:.0f} kWh")
            print(f"Solar/Load ratio: {total_solar/total_load:.2f}")
            
            if total_solar < total_load * 0.3:
                print(f"⚠️ LIKELY CAUSE: Insufficient solar generation")
            elif charge_events < 100:
                print(f"⚠️ LIKELY CAUSE: Algorithm not triggering charging")
            else:
                print(f"⚠️ LIKELY CAUSE: Peak preparation limits or SAM override")
        
        # Print summary of daily predictions
        if daily_predictions:
            print(f"\n📈 Peak Prediction Summary ({len(daily_predictions)} days):")
            print("=" * 60)
            
            total_peak_load = sum(pred['peak_load_kwh'] for pred in daily_predictions.values())
            total_battery_ready = sum(pred['battery_ready_kwh'] for pred in daily_predictions.values())
            avg_coverage = (total_battery_ready / total_peak_load * 100) if total_peak_load > 0 else 0
            
            print(f"Total peak load (all days): {total_peak_load:.2f} kWh")
            print(f"Total battery available: {total_battery_ready:.2f} kWh")
            print(f"Average peak coverage: {avg_coverage:.1f}%")
            
            # Count days with good/poor preparation
            well_prepared = sum(1 for pred in daily_predictions.values() 
                              if pred['battery_ready_kwh'] >= pred['peak_target_kwh'] * 0.9)
            under_prepared = len(daily_predictions) - well_prepared
            
            print(f"Well-prepared days: {well_prepared}/{len(daily_predictions)}")
            print(f"Under-prepared days: {under_prepared}/{len(daily_predictions)}")
            
            if under_prepared > 0:
                print(f"⚠️ Strategy may need adjustment for better peak coverage")
            else:
                print(f"✅ Peak strategy performing well!")
        
        # SOC violation analysis
        soc_data = [log['soc'] for log in dispatch_log]
        min_soc_observed = min(soc_data)
        low_soc_hours = sum(1 for soc in soc_data if soc < 15.0)
        critical_soc_hours = sum(1 for soc in soc_data if soc < 10.0)
        
        print(f"\n🔋 SOC Analysis Summary:")
        print("=" * 30)
        print(f"Minimum SOC observed: {min_soc_observed:.2f}%")
        print(f"Hours below 15% SOC: {low_soc_hours}")
        print(f"Hours below 10% SOC: {critical_soc_hours}")
        
        if critical_soc_hours > 0:
            print(f"🚨 CRITICAL: Battery went below 10% SOC for {critical_soc_hours} hours!")
            print(f"   This indicates algorithm or SAM configuration issues")
        elif low_soc_hours > 0:
            print(f"⚠️ WARNING: Battery went below 15% SOC for {low_soc_hours} hours")
            print(f"   Consider more conservative discharge limits")
        else:
            print(f"✅ SOC stayed within safe operating range")
        
        return charge_schedule, discharge_schedule, gridcharge_schedule

    def generate_custom_dispatch_schedule_simple(self, load_profile, solar_profile):
        """
        Simplified rule-based schedule that meets the project goals:
        - Keep SOC within 20%–80% using a shadow battery state.
        - Charge using solar during the day for the amount needed in the 4–9pm block
          (net of solar in those hours), capped by usable capacity.
        - Discharge only during 4–9pm to serve load down to the 20% SOC floor.

        Returns: (charge_schedule, discharge_schedule, gridcharge_schedule)
        """
        hours = len(load_profile)
        charge_schedule = np.zeros(hours)
        discharge_schedule = np.zeros(hours)
        gridcharge_schedule = np.zeros(hours)

        # Shadow battery state
        soc = 50.0
        energy_kwh = soc / 100.0 * self.battery_capacity
        usable_kwh = (self.max_soc - self.min_soc) / 100.0 * self.battery_capacity
        max_charge_kw = 5.0
        max_discharge_kw = 5.0

        log_rows = []

        for h in range(hours):
            hod = h % 24
            day_start = (h // 24) * 24
            day_end = min(day_start + 24, hours)
            peak_start = day_start + 16  # 4 PM
            peak_end = min(day_start + 21, hours)  # up to 9 PM (exclusive)

            # Daily net need in peak block (load minus solar, not below 0)
            if peak_start < peak_end:
                peak_load = np.array(load_profile[peak_start:peak_end])
                peak_solar = np.array(solar_profile[peak_start:peak_end]) if solar_profile else np.zeros_like(peak_load)
                net_need_kwh = float(np.maximum(peak_load - peak_solar, 0).sum())
            else:
                net_need_kwh = 0.0
            target_kwh = min(net_need_kwh, usable_kwh)

            available_for_peak = max(0.0, energy_kwh - (self.min_soc / 100.0 * self.battery_capacity))

            load = load_profile[h]
            solar = solar_profile[h] if solar_profile else 0.0
            is_peak = 16 <= hod <= 20

            charge = 0.0
            discharge = 0.0
            gridcharge = 0.0

            if is_peak and load > 0:
                need_now = min(target_kwh, load)
                can_discharge = max(0.0, energy_kwh - (self.min_soc / 100.0 * self.battery_capacity))
                d_kwh = min(need_now, can_discharge, max_discharge_kw)
                if d_kwh > 0:
                    discharge = 1.0
                    energy_kwh -= d_kwh
                    soc = (energy_kwh / self.battery_capacity) * 100.0
            else:
                need_for_peak = max(0.0, target_kwh - available_for_peak)
                if solar > 0 and need_for_peak > 0 and soc < self.max_soc:
                    room_kwh = (self.max_soc / 100.0 * self.battery_capacity) - energy_kwh
                    c_kwh = min(solar, room_kwh, max_charge_kw, need_for_peak)
                    if c_kwh > 0:
                        charge = 1.0
                        energy_kwh += c_kwh
                        soc = (energy_kwh / self.battery_capacity) * 100.0

            charge_schedule[h] = charge
            discharge_schedule[h] = discharge
            gridcharge_schedule[h] = gridcharge

            log_rows.append({
                'hour': h,
                'hour_of_day': hod,
                'soc': soc,
                'load': load,
                'solar': solar,
                'is_peak': is_peak,
                'net_need_peak_kwh': target_kwh,
                'charge': charge,
                'discharge': discharge,
                'gridcharge': gridcharge,
                'action': (1 if discharge > 0 else (-1 if charge > 0 else 0))
            })

        self.dispatch_log = pd.DataFrame(log_rows)
        return charge_schedule, discharge_schedule, gridcharge_schedule
    
    def analyze_dispatch_strategy(self):
        """Analyze the generated dispatch strategy"""
        if not hasattr(self, 'dispatch_log'):
            print("No dispatch log available. Run generate_custom_dispatch_schedule first.")
            return
        
        log = self.dispatch_log
        
        # Calculate statistics
        total_charge_events = (log['charge'] > 0).sum()
        total_discharge_events = (log['discharge'] > 0).sum()
        total_gridcharge_events = (log['gridcharge'] > 0).sum()
        
        avg_discharge_rate = log[log['discharge'] > 0]['rate'].mean()
        avg_gridcharge_rate = log[log['gridcharge'] > 0]['rate'].mean()
        
        min_soc = log['soc'].min()
        max_soc = log['soc'].max()
        avg_soc = log['soc'].mean()
        
        print("Custom Dispatch Strategy Analysis")
        print("=" * 45)
        print(f"Charge events (solar):        {total_charge_events:,} hours")
        print(f"Discharge events:             {total_discharge_events:,} hours")
        print(f"Grid charge events:           {total_gridcharge_events:,} hours")
        print()
        print(f"Avg discharge rate:           ${avg_discharge_rate:.3f}/kWh" if not np.isnan(avg_discharge_rate) else "Avg discharge rate:           N/A")
        print(f"Avg grid charge rate:         ${avg_gridcharge_rate:.3f}/kWh" if not np.isnan(avg_gridcharge_rate) else "Avg grid charge rate:         N/A")
        print(f"Battery cycle cost:           ${self.cycle_cost:.3f}/kWh")
        print()
        print(f"SOC range: {min_soc:.1f}% - {max_soc:.1f}% (avg: {avg_soc:.1f}%)")
        
        return {
            'charge_events': total_charge_events,
            'discharge_events': total_discharge_events,
            'gridcharge_events': total_gridcharge_events,
            'avg_discharge_rate': avg_discharge_rate,
            'avg_gridcharge_rate': avg_gridcharge_rate,
            'min_soc': min_soc,
            'max_soc': max_soc,
            'avg_soc': avg_soc
        }


def initialize_solar(weather_file, load_profile, charge_schedule, discharge_schedule, gridcharge_schedule):
    """Initialize SAM solar model with configuration"""
    print("DEBUG: Starting SAM configuration...")
        
    # Load solar resource data
    print("DEBUG: Loading solar resource data...")
    solar_resource_data = tools.SAM_CSV_to_solar_data(weather_file)
    print(f"DEBUG: Solar resource data loaded, keys: {list(solar_resource_data.keys())[:5]}...")
    
    # Calculate system capacity (simplified)
    annual_load_kwh = sum(load_profile)
    system_capacity = annual_load_kwh / 1200  # Rough sizing: 1200 kWh/kW annually
    
    print(f"SAM Configuration:")
    print(f"  Annual load: {annual_load_kwh:,.0f} kWh")
    print(f"  Solar system size: {system_capacity:.1f} kW")
    
    # === Solar Model Setup ===
    print("DEBUG: Initializing solar model...")
    solar = pvwatts.new()
    print(f"DEBUG: Solar model created: {type(solar)}")
    
    # Load SAM solar configuration with debugging
    print("DEBUG: Loading solar configuration with custom dispatch...")
    solar_config_file = "SAM_configuration_with_battery_custom_dispatch/untitled__1__pvwattsv8.json"
    
    if not os.path.exists(solar_config_file):
        print(f"DEBUG: Solar config file not found: {solar_config_file}")
        return None
    
    with open(solar_config_file, 'r') as file:
        solar_config = json.load(file)
        print(f"DEBUG: Solar config loaded, {len(solar_config)} parameters")
        
        # Apply configuration with error checking
        print("DEBUG: Applying solar configuration...")
        skipped_params = []
        applied_params = []
        
        for k, v in solar_config.items():
            if k in ["number_inputs"]:
                skipped_params.append(k)
                continue
                
            try:
                solar.value(k, v)
                applied_params.append(k)
            except Exception as e:
                print(f"DEBUG: Failed to set solar parameter '{k}': {e}")
                skipped_params.append(k)
        
        print(f"DEBUG: Applied {len(applied_params)} solar parameters")
        if skipped_params:
            print(f"DEBUG: Skipped {len(skipped_params)} solar parameters")

    # Set solar parameters with debugging
    print("DEBUG: Setting solar resource data...")
    try:
        solar.SolarResource.solar_resource_data = solar_resource_data
        print("DEBUG: Solar resource data set")
    except Exception as e:
        print(f"DEBUG: Failed to set solar resource data: {e}")
        return None
    
    print("DEBUG: Setting system capacity...")
    try:
        solar.SystemDesign.system_capacity = system_capacity
        print(f"DEBUG: System capacity set to {system_capacity:.1f} kW")
    except Exception as e:
        print(f"DEBUG: Failed to set system capacity: {e}")
        return None
    
    print("DEBUG: Setting degradation...")
    try:
        solar.Lifetime.dc_degradation = [0.5]  # 0.5% annual degradation
        print("DEBUG: Degradation set")
    except Exception as e:
        print(f"DEBUG: Failed to set degradation: {e}")
        return None
    
    return solar


def initialize_storage(weather_file, load_profile, charge_schedule, discharge_schedule, gridcharge_schedule, solar):
    """Initialize SAM battery storage model"""
    # === Battery Model Setup ===
    print("DEBUG: Creating battery model...")
    try:
        battery = battery_model.from_existing(solar)
        print(f"DEBUG: Battery model created: {type(battery)}")
    except Exception as e:
        print(f"DEBUG: Failed to create battery model: {e}")
        return None
    
    # Load SAM battery configuration with debugging
    print("DEBUG: Loading battery configuration...")
    battery_config_file = "SAM_configuration_with_battery_custom_dispatch/untitled__1__battwatts.json"
    
    if not os.path.exists(battery_config_file):
        print(f"DEBUG: Battery config file not found: {battery_config_file}")
        return None
        
    with open(battery_config_file, 'r') as file:
        battery_config = json.load(file)
        print(f"DEBUG: Battery config loaded, {len(battery_config)} parameters")
        
        # Apply configuration with error checking
        print("DEBUG: Applying battery configuration...")
        skipped_battery_params = []
        applied_battery_params = []
        
        for k, v in battery_config.items():
            if k in ["number_inputs"]:
                skipped_battery_params.append(k)
                continue
                
            try:
                battery.value(k, v)
                applied_battery_params.append(k)
            except Exception as e:
                print(f"DEBUG: Failed to set battery parameter '{k}': {e}")
                skipped_battery_params.append(k)
        
        print(f"DEBUG: Applied {len(applied_battery_params)} battery parameters")
        if skipped_battery_params:
            print(f"DEBUG: Skipped {len(skipped_battery_params)} battery parameters")
    
    # Set load profile with debugging
    print("DEBUG: Setting load profile...")
    try:
        battery.Battery.assign({'load': load_profile})
        print(f"DEBUG: Load profile set, {len(load_profile)} hours")
    except Exception as e:
        print(f"DEBUG: Failed to set load profile: {e}")
        return None
    
    return battery


def initialize_custom_dispatch(solar, battery, load_profile, charge_schedule, discharge_schedule, gridcharge_schedule):
    """Configure SAM with custom dispatch schedules"""
    # === Configure Custom Dispatch ===
    print("DEBUG: Configuring custom dispatch...")
    
    # Load battery config for reference
    battery_config_file = "SAM_configuration_with_battery_custom_dispatch/untitled__1__battwatts.json"
    with open(battery_config_file, 'r') as file:
        battery_config = json.load(file)
    
    # Validate schedule lengths
    print(f"DEBUG: Validating schedule lengths...")
    print(f"  Load profile: {len(load_profile)} hours")
    print(f"  Charge schedule: {len(charge_schedule)} hours")
    print(f"  Discharge schedule: {len(discharge_schedule)} hours")
    print(f"  Grid charge schedule: {len(gridcharge_schedule)} hours")
    
    if not all(len(s) == len(load_profile) for s in [charge_schedule, discharge_schedule, gridcharge_schedule]):
        print("DEBUG: Schedule length mismatch!")
        return None

    # Set custom dispatch schedules
    print("DEBUG: Setting custom dispatch schedules...")
    try:
        # Convert schedules to lists if they're numpy arrays
        discharge_list = discharge_schedule.tolist() if hasattr(discharge_schedule, 'tolist') else list(discharge_schedule)
        charge_list = charge_schedule.tolist() if hasattr(charge_schedule, 'tolist') else list(charge_schedule)
        gridcharge_list = gridcharge_schedule.tolist() if hasattr(gridcharge_schedule, 'tolist') else list(gridcharge_schedule)
        
        # Convert our optimization schedules to SAM's simple format
        # SAM expects: positive = discharge, negative = charge, zero = no action
        sam_dispatch_array = []
        
        for h in range(len(load_profile)):
            discharge_signal = discharge_list[h]
            charge_signal = charge_list[h] 
            gridcharge_signal = gridcharge_list[h]
            
            # Decision logic: prioritize the strongest signal
            if discharge_signal > 0.1:  # Threshold to avoid tiny values
                # Want to discharge: positive value in SAM
                sam_dispatch_array.append(1)
            elif charge_signal > 0.1 or gridcharge_signal > 0.1:
                # Want to charge (from solar or grid): negative value in SAM
                sam_dispatch_array.append(-1)
            else:
                # No strong preference: let SAM decide automatically
                sam_dispatch_array.append(0)
        
        print(f"DEBUG: Converted to SAM format: {len(sam_dispatch_array)} values")
        
        # Count actions for verification
        discharge_hours = sum(1 for x in sam_dispatch_array if x > 0)
        charge_hours = sum(1 for x in sam_dispatch_array if x < 0)
        auto_hours = sum(1 for x in sam_dispatch_array if x == 0)
        
        print(f"DEBUG: SAM dispatch summary:")
        print(f"  Discharge hours: {discharge_hours}")
        print(f"  Charge hours: {charge_hours}")
        print(f"  Auto hours: {auto_hours}")
        
        # Set the custom dispatch array
        battery.Battery.batt_custom_dispatch = sam_dispatch_array
        
        # Verify it was set correctly
        check_dispatch = battery.Battery.batt_custom_dispatch
        print(f"DEBUG: Custom dispatch successfully set!")
        print(f"  Array length: {len(check_dispatch)}")
        print(f"  Sample values: {check_dispatch[:10]}")
        
    except Exception as e:
        print(f"DEBUG: Failed to set custom dispatch schedules: {e}")
        print(f"  Error type: {type(e)}")
        print(f"  Error details: {str(e)}")
        return None
    
    # Try to enable advanced dispatch options through config
    print("DEBUG: Setting additional dispatch parameters...")
    
    # Set any additional dispatch parameters found in config
    additional_dispatch_settings = {
        'batt_dispatch_auto_can_gridcharge': 1,
        'batt_dispatch_auto_can_charge': 1,
        'batt_dispatch_auto_btm_can_discharge_to_grid': 0,  # Don't discharge to grid
    }
    
    for param, value in additional_dispatch_settings.items():
        try:
            if param in battery_config or hasattr(battery.Battery, param):
                setattr(battery.Battery, param, value)
                print(f"DEBUG: Set {param} = {value}")
        except Exception as e:
            print(f"DEBUG: Failed to set {param}: {e}")
    
    print(f"DEBUG: Custom dispatch configuration complete")


def run_sam_simulation(solar, battery):
    """Execute SAM simulation and extract results"""
    # === Run SAM Simulation ===
    print("\nRunning SAM simulation...")
    
    print("DEBUG: Executing solar model...")
    try:
        solar.execute(0)
        print("DEBUG: Solar execution completed")
    except Exception as e:
        print(f"DEBUG: Solar execution failed: {e}")
        return None
    
    print("DEBUG: Executing battery model...")
    try:
        battery.execute(0)
        print("DEBUG: Battery execution completed")
    except Exception as e:
        print(f"DEBUG: Battery execution failed: {e}")
        print(f"  Error type: {type(e)}")
        print(f"  Error details: {str(e)}")
        import traceback
        traceback.print_exc()
        return None
    
    print("SAM simulation completed")
    
    # === Extract Results ===
    print("DEBUG: Extracting results...")
    try:
        results = {
            'load_profile': battery.Battery.load,
            'system_to_load': battery.Outputs.system_to_load,
            'battery_to_load': battery.Outputs.batt_to_load,
            'grid_to_load': battery.Outputs.grid_to_load,
            'grid_to_batt': battery.Outputs.grid_to_batt,
            'system_to_batt': battery.Outputs.system_to_batt,
            'system_to_grid': battery.Outputs.system_to_grid,
            'battery_soc': battery.Outputs.batt_SOC,
            'solar_capacity': solar.SystemDesign.system_capacity,
            'battery_capacity': battery.Outputs.batt_bank_installed_capacity
        }
        
        print(f"DEBUG: Results extracted successfully")
        print(f"  Solar capacity: {results['solar_capacity']:.1f} kW")
        print(f"  Battery capacity: {results['battery_capacity']:.1f} kWh")
        print(f"  Load profile length: {len(results['load_profile'])}")
        print(f"  SOC range: {min(results['battery_soc']):.1f}% - {max(results['battery_soc']):.1f}%")
        
        return results
        
    except Exception as e:
        print(f"DEBUG: Failed to extract results: {e}")
        return None


def run_sam_with_custom_dispatch(weather_file, load_profile, charge_schedule, discharge_schedule, gridcharge_schedule):
    """
    Run SAM with custom dispatch schedule
    """
    try:
        solar = initialize_solar(weather_file, load_profile, charge_schedule, discharge_schedule, gridcharge_schedule)
        if solar is None:
            return None
            
        battery = initialize_storage(weather_file, load_profile, charge_schedule, discharge_schedule, gridcharge_schedule, solar)
        if battery is None:
            return None
            
        initialize_custom_dispatch(solar, battery, load_profile, charge_schedule, discharge_schedule, gridcharge_schedule)
        
        return run_sam_simulation(solar, battery)
        
    except Exception as e:
        print(f"DEBUG: Unexpected error in SAM simulation: {e}")
        print(f"  Error type: {type(e)}")
        print(f"  Error details: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


def compare_dispatch_results(reference_data, custom_data, dispatch_log):
    """
    Compare reference SAM results with custom dispatch results
    """
    if reference_data is None or custom_data is None:
        print("Cannot compare results - missing data")
        return
    
    print("Dispatch Results Comparison")
    print("=" * 50)
    
    # Convert custom results to series for easier analysis
    def safe_convert_to_list(data):
        """Safely convert data to list for analysis"""
        if isinstance(data, (list, tuple)):
            return list(data)
        elif hasattr(data, 'tolist'):
            return data.tolist()
        elif hasattr(data, '__iter__'):
            return list(data)
        else:
            return [data] * 8760  # Fallback for scalar values
    
    custom_df = pd.DataFrame({
        'Load Profile': safe_convert_to_list(custom_data['load_profile']),
        'System to Load': safe_convert_to_list(custom_data['system_to_load']),
        'Battery to Load': safe_convert_to_list(custom_data['battery_to_load']),
        'Grid to Load': safe_convert_to_list(custom_data['grid_to_load']),
        'Battery SOC': safe_convert_to_list(custom_data['battery_soc']),
        'Grid to Battery': safe_convert_to_list(custom_data['grid_to_batt'])
    })
    
    # Annual summaries
    ref_stats = {
        'grid_kwh': reference_data['Grid to Load'].sum(),
        'battery_discharge_kwh': reference_data['Battery to Load'].sum(),
        'battery_charge_kwh': (reference_data['System to Battery'] + reference_data['Grid to Battery']).sum(),
        'min_soc': reference_data['Battery SOC'].min(),
        'avg_soc': reference_data['Battery SOC'].mean(),
        'solar_kwh': reference_data['System to Load'].sum()
    }
    
    # Safely calculate custom stats
    try:
        system_to_batt_data = safe_convert_to_list(custom_data['system_to_batt'])
        custom_battery_charge = custom_df['Grid to Battery'].sum() + sum(system_to_batt_data)
    except Exception as e:
        print(f"DEBUG: Error calculating battery charge: {e}")
        custom_battery_charge = custom_df['Grid to Battery'].sum()
    
    custom_stats = {
        'grid_kwh': custom_df['Grid to Load'].sum(),
        'battery_discharge_kwh': custom_df['Battery to Load'].sum(),
        'battery_charge_kwh': custom_battery_charge,
        'min_soc': custom_df['Battery SOC'].min(),
        'avg_soc': custom_df['Battery SOC'].mean(),
        'solar_kwh': custom_df['System to Load'].sum()
    }
    
    print(f"{'Metric':<25} {'Reference':<15} {'Custom':<15} {'Difference':<15}")
    print("-" * 70)
    
    metrics = [
        ('Grid Usage (kWh)', 'grid_kwh'),
        ('Battery Discharge (kWh)', 'battery_discharge_kwh'),
        ('Battery Charge (kWh)', 'battery_charge_kwh'),
        ('Min SOC (%)', 'min_soc'),
        ('Avg SOC (%)', 'avg_soc'),
        ('Solar Production (kWh)', 'solar_kwh')
    ]
    
    for label, key in metrics:
        ref_val = ref_stats[key]
        custom_val = custom_stats[key]
        diff = custom_val - ref_val
        
        if 'kwh' in key.lower():
            print(f"{label:<25} {ref_val:<15.0f} {custom_val:<15.0f} {diff:<15.0f}")
        else:
            print(f"{label:<25} {ref_val:<15.1f} {custom_val:<15.1f} {diff:<15.1f}")
    
    # Calculate percentage improvements (with safety checks)
    grid_reduction_pct = 0
    battery_increase_pct = 0
    
    try:
        if ref_stats['grid_kwh'] > 0:
            grid_reduction_pct = (ref_stats['grid_kwh'] - custom_stats['grid_kwh']) / ref_stats['grid_kwh'] * 100
        
        if ref_stats['battery_discharge_kwh'] > 0:
            battery_increase_pct = (custom_stats['battery_discharge_kwh'] - ref_stats['battery_discharge_kwh']) / ref_stats['battery_discharge_kwh'] * 100
    except Exception as e:
        print(f"DEBUG: Error calculating percentages: {e}")
    
    print("\nKey Improvements:")
    print(f"Grid usage reduction: {grid_reduction_pct:.1f}%")
    print(f"Battery utilization increase: {battery_increase_pct:.1f}%")
    print(f"SOC utilization improvement: {ref_stats['avg_soc'] - custom_stats['avg_soc']:.1f} percentage points")
    
    return {
        'reference_stats': ref_stats,
        'custom_stats': custom_stats,
        'grid_reduction_pct': grid_reduction_pct,
        'battery_increase_pct': battery_increase_pct
    }


def calculate_economic_benefits(custom_results, reference_data, dispatch_log, rate_plan):
    """
    Calculate economic benefits of custom dispatch vs reference
    """
    if custom_results is None:
        print("Cannot calculate benefits without custom results")
        return None
    
    # Initialize generator to get hourly rates
    generator = CustomDispatchScheduleGenerator(rate_plan)
    hourly_rates = generator.get_hourly_rates()
    
    # Calculate costs for custom dispatch
    custom_grid_usage = custom_results['grid_to_load']
    custom_annual_cost = sum(grid * rate for grid, rate in zip(custom_grid_usage, hourly_rates))
    
    # Calculate costs for reference (if available)
    if reference_data is not None:
        ref_grid_usage = reference_data['Grid to Load'].values
        ref_annual_cost = sum(grid * rate for grid, rate in zip(ref_grid_usage, hourly_rates))
        annual_savings = ref_annual_cost - custom_annual_cost
    else:
        ref_annual_cost = None
        annual_savings = None
    
    # Calculate dispatch efficiency metrics
    total_discharge_events = (dispatch_log['discharge'] > 0).sum()
    avg_discharge_rate = dispatch_log[dispatch_log['discharge'] > 0]['rate'].mean()
    
    total_gridcharge_events = (dispatch_log['gridcharge'] > 0).sum()
    avg_gridcharge_rate = dispatch_log[dispatch_log['gridcharge'] > 0]['rate'].mean()
    
    # Rate arbitrage opportunities
    if not pd.isna(avg_discharge_rate) and not pd.isna(avg_gridcharge_rate):
        rate_spread = avg_discharge_rate - avg_gridcharge_rate
    else:
        rate_spread = 0
    
    print("Economic Analysis: Custom Dispatch")
    print("=" * 45)
    print(f"Annual electricity cost (custom):  ${custom_annual_cost:,.2f}")
    if ref_annual_cost:
        print(f"Annual electricity cost (reference): ${ref_annual_cost:,.2f}")
        print(f"Annual savings:                    ${annual_savings:,.2f}")
        print(f"Savings percentage:                {annual_savings/ref_annual_cost*100:.1f}%")
    
    print("\nDispatch Strategy Analysis:")
    print(f"Discharge events:                  {total_discharge_events:,} hours")
    print(f"Avg discharge rate:                ${avg_discharge_rate:.3f}/kWh" if not pd.isna(avg_discharge_rate) else "Avg discharge rate:                N/A")
    
    print(f"Grid charge events:                {total_gridcharge_events:,} hours")
    print(f"Avg grid charge rate:              ${avg_gridcharge_rate:.3f}/kWh" if not pd.isna(avg_gridcharge_rate) else "Avg grid charge rate:              N/A")
    
    if rate_spread > 0:
        print(f"Rate arbitrage spread:             ${rate_spread:.3f}/kWh")
        print(f"Cycle cost threshold:              ${generator.cycle_cost:.3f}/kWh")
        
        if avg_discharge_rate > generator.cycle_cost:
            print("Discharge strategy is economically justified")
        else:
            print("Discharge rate below cycle cost threshold")
    
    return {
        'custom_annual_cost': custom_annual_cost,
        'ref_annual_cost': ref_annual_cost,
        'annual_savings': annual_savings,
        'discharge_events': total_discharge_events,
        'gridcharge_events': total_gridcharge_events,
        'avg_discharge_rate': avg_discharge_rate,
        'avg_gridcharge_rate': avg_gridcharge_rate,
        'rate_spread': rate_spread
    }


def plot_custom_dispatch_analysis(custom_results, dispatch_log, reference_data=None, month="January", week_offset=0):
    """
    Create comprehensive visualization of custom dispatch behavior
    
    Args:
        custom_results: SAM simulation results
        dispatch_log: Algorithm dispatch decisions
        reference_data: Reference SAM data for comparison
        month: Month name for title (e.g., "January", "July")
        week_offset: Which week of the year to analyze (0 = first week)
    """
    if custom_results is None:
        print("Cannot create plots without custom dispatch results")
        return
    
    # Calculate week hours based on offset
    week_hours = 168
    start_hour = week_offset * 24  # Start of the target week
    end_hour = start_hour + week_hours
    hours = range(week_hours)
    
    # Extract week data based on offset
    max_hours = min(len(custom_results['load_profile']), len(dispatch_log))
    actual_end = min(end_hour, max_hours)
    actual_start = min(start_hour, max_hours - week_hours) if max_hours >= week_hours else 0
    actual_week_hours = actual_end - actual_start
    
    custom_week = {
        'load': custom_results['load_profile'][actual_start:actual_end],
        'solar': custom_results['system_to_load'][actual_start:actual_end],
        'battery_soc': custom_results['battery_soc'][actual_start:actual_end],
        'battery_discharge': custom_results['battery_to_load'][actual_start:actual_end],
        'grid_usage': custom_results['grid_to_load'][actual_start:actual_end],
        'grid_to_battery': custom_results['grid_to_batt'][actual_start:actual_end]
    }
    
    dispatch_week = dispatch_log.iloc[actual_start:actual_end]
    
    # Adjust hours range for actual data length
    hours = range(len(custom_week['load']))
    week_hours = len(custom_week['load'])
    
    # Create subplots - extra row for solar analysis and peak predictions
    fig, axes = plt.subplots(5, 2, figsize=(16, 20))
    week_start_day = (actual_start // 24) + 1
    fig.suptitle(f'SAM Custom Dispatch Analysis: Week Starting Day {week_start_day} ({month})', fontsize=16, fontweight='bold')
    
    # 1. Battery SOC with dispatch events
    ax1 = axes[0, 0]
    ax1.plot(hours, custom_week['battery_soc'], 'b-', linewidth=2, label='Battery SOC')
    
    # Highlight dispatch events
    charge_hours = dispatch_week[dispatch_week['charge'] > 0].index
    discharge_hours = dispatch_week[dispatch_week['discharge'] > 0].index  
    gridcharge_hours = dispatch_week[dispatch_week['gridcharge'] > 0].index
    
    for h in charge_hours:
        if h < week_hours:
            ax1.axvline(x=h, color='green', alpha=0.3, linewidth=0.8)
    for h in discharge_hours:
        if h < week_hours:
            ax1.axvline(x=h, color='red', alpha=0.3, linewidth=0.8)
    for h in gridcharge_hours:
        if h < week_hours:
            ax1.axvline(x=h, color='orange', alpha=0.3, linewidth=0.8)
    
    # Mark peak hours and SOC limits
    week_days = set(h // 24 for h in hours if h < week_hours)
    for day in week_days:
        peak_start = day * 24 + 16
        peak_end = day * 24 + 21
        if peak_start < week_hours:
            peak_end = min(peak_end, week_hours)
            ax1.axvspan(peak_start, peak_end, alpha=0.2, color='yellow', label='Peak Hours' if day == min(week_days) else "")
    
    ax1.axhline(y=20, color='red', linestyle='--', alpha=0.7, label='Min Peak SOC (20%)')
    ax1.axhline(y=80, color='orange', linestyle='--', alpha=0.7, label='Max Peak SOC (80%)')
    ax1.set_title('Battery SOC with Dispatch Events', fontweight='bold')
    ax1.set_ylabel('SOC (%)')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # 2. Electricity rates vs dispatch decisions
    ax2 = axes[0, 1]
    rates_week = dispatch_week['rate'][:week_hours].values
    ax2.plot(hours, rates_week, 'purple', linewidth=2, label='Electricity Rate')
    
    # Get cycle cost from dispatch generator (need to access it)
    cycle_cost = 0.185  # Default value, should match dispatch generator
    ax2.axhline(y=cycle_cost, color='red', linestyle='--', alpha=0.7, 
               label=f'Cycle Cost (${cycle_cost:.3f}/kWh)')
    
    # Mark discharge events with scatter plot
    discharge_mask = dispatch_week['discharge'][:week_hours] > 0
    if discharge_mask.any():
        discharge_hours_scatter = [h for h in hours if h < len(discharge_mask) and discharge_mask.iloc[h]]
        discharge_rates = [rates_week[h] for h in discharge_hours_scatter]
        ax2.scatter(discharge_hours_scatter, discharge_rates, 
                   c='red', alpha=0.8, s=30, label='Discharge Events')
    
    ax2.set_title('Rates vs Discharge Decisions', fontweight='bold')
    ax2.set_ylabel('Rate ($/kWh)')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    
    # 3. Energy flows stacked area chart
    ax3 = axes[1, 0]
    solar_data = np.array(custom_week['solar'])
    battery_data = np.array(custom_week['battery_discharge'])
    grid_data = np.array(custom_week['grid_usage'])
    load_data = np.array(custom_week['load'])
    
    # Create stacked areas for energy sources
    ax3.fill_between(hours, 0, solar_data, alpha=0.7, color='gold', label='Solar')
    ax3.fill_between(hours, solar_data, solar_data + battery_data, 
                    alpha=0.7, color='green', label='Battery Discharge')
    ax3.fill_between(hours, solar_data + battery_data, 
                    solar_data + battery_data + grid_data,
                    alpha=0.7, color='red', label='Grid')
    
    # Plot total load as a line
    ax3.plot(hours, load_data, 'k-', linewidth=2, label='Total Load')
    
    ax3.set_title('Energy Sources (Custom Dispatch)', fontweight='bold')
    ax3.set_ylabel('Power (kW)')
    ax3.legend()
    ax3.grid(True, alpha=0.3)
    
    # 4. Grid charging events with rate overlay
    ax4 = axes[1, 1]
    grid_to_battery = np.array(custom_week['grid_to_battery'])
    ax4.bar(hours, grid_to_battery, alpha=0.7, color='orange', label='Grid to Battery')
    
    # Add rate overlay on secondary y-axis
    ax4_rate = ax4.twinx()
    ax4_rate.plot(hours, rates_week * 5, 'purple', linewidth=1, alpha=0.7, label='Rate (×5)')
    ax4_rate.set_ylabel('Rate ($/kWh × 5)', color='purple')
    
    ax4.set_title('Grid Charging Events', fontweight='bold')
    ax4.set_ylabel('Power (kW)')
    ax4.legend(loc='upper left')
    ax4_rate.legend(loc='upper right')
    ax4.grid(True, alpha=0.3)
    
    # 5. Comparison with reference (if available)
    ax5 = axes[2, 0]
    if reference_data is not None:
        ref_week_soc = reference_data['Battery SOC'].iloc[:week_hours].values
        ax5.plot(hours, ref_week_soc, 'b--', linewidth=2, alpha=0.7, label='Reference SAM')
        ax5.plot(hours, custom_week['battery_soc'], 'g-', linewidth=2, label='Custom Dispatch')
        ax5.set_title('SOC Comparison: Reference vs Custom', fontweight='bold')
        
        # Add difference area
        soc_diff = np.array(custom_week['battery_soc']) - ref_week_soc
        ax5.fill_between(hours, ref_week_soc, custom_week['battery_soc'], 
                        where=(soc_diff > 0), alpha=0.3, color='green', label='Custom Higher')
        ax5.fill_between(hours, ref_week_soc, custom_week['battery_soc'], 
                        where=(soc_diff < 0), alpha=0.3, color='red', label='Reference Higher')
    else:
        ax5.plot(hours, custom_week['battery_soc'], 'g-', linewidth=2, label='Custom Dispatch SOC')
        ax5.set_title('Custom Dispatch Battery SOC', fontweight='bold')
    
    ax5.set_ylabel('SOC (%)')
    ax5.set_xlabel('Hours')
    ax5.legend()
    ax5.grid(True, alpha=0.3)
    
    # 6. Economic benefit visualization
    ax6 = axes[2, 1]
    
    # Calculate hourly savings (simplified)
    if reference_data is not None:
        ref_grid_week = reference_data['Grid to Load'].iloc[:week_hours].values
        custom_grid_week = np.array(custom_week['grid_usage'])
        hourly_savings = (ref_grid_week - custom_grid_week) * rates_week
        cumulative_savings = np.cumsum(hourly_savings)
        
        ax6.plot(hours, cumulative_savings, 'g-', linewidth=2, label='Cumulative Savings')
        ax6.fill_between(hours, 0, cumulative_savings, alpha=0.3, color='green')
        
        # Add hourly savings as bars
        positive_savings = np.where(hourly_savings > 0, hourly_savings, 0)
        negative_savings = np.where(hourly_savings < 0, hourly_savings, 0)
        ax6.bar(hours, positive_savings, alpha=0.6, color='green', width=0.8)
        ax6.bar(hours, negative_savings, alpha=0.6, color='red', width=0.8)
        
        ax6.set_title('Economic Benefits', fontweight='bold')
        ax6.set_ylabel('Savings ($)')
        
        # Add summary text
        total_savings = cumulative_savings[-1]
        ax6.text(0.05, 0.95, f'Week Total: ${total_savings:.2f}', 
                transform=ax6.transAxes, fontsize=10, verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
    else:
        # Show dispatch activity level
        dispatch_intensity = (dispatch_week['discharge'][:week_hours] + 
                            dispatch_week['charge'][:week_hours] + 
                            dispatch_week['gridcharge'][:week_hours])
        
        bars = ax6.bar(hours, dispatch_intensity, alpha=0.7, color='blue', label='Dispatch Activity')
        ax6.set_title('Dispatch Activity Level', fontweight='bold')
        ax6.set_ylabel('Activity Level')
        
        # Color bars by activity type
        for i, (h, activity) in enumerate(zip(hours, dispatch_intensity)):
            if h < len(dispatch_week):
                if dispatch_week['discharge'].iloc[h] > 0:
                    bars[i].set_color('red')
                elif dispatch_week['charge'].iloc[h] > 0 or dispatch_week['gridcharge'].iloc[h] > 0:
                    bars[i].set_color('green')
    
    ax6.set_xlabel('Hours')
    ax6.legend()
    ax6.grid(True, alpha=0.3)
    
    # 7. Solar Generation Analysis - Check for clipping
    ax7 = axes[3, 0]
    
    # Get the original solar profile from dispatch log (before any allocation)
    original_solar_week = dispatch_week['solar'][:week_hours].values
    system_to_load_week = np.array(custom_week['solar'])  # What actually went to load
    system_to_batt_week = np.array([0] * week_hours)  # Initialize
    
    # Try to get system to battery data if available
    try:
        if 'system_to_batt' in custom_results:
            system_to_batt_data = custom_results['system_to_batt']
            if hasattr(system_to_batt_data, '__len__') and len(system_to_batt_data) >= week_hours:
                system_to_batt_week = np.array(system_to_batt_data[:week_hours])
    except:
        pass
    
    # Calculate total solar utilization
    total_solar_used = system_to_load_week + system_to_batt_week
    
    # Plot solar generation components
    ax7.fill_between(hours, 0, system_to_load_week, alpha=0.7, color='gold', label='Solar to Load')
    ax7.fill_between(hours, system_to_load_week, total_solar_used, 
                    alpha=0.7, color='orange', label='Solar to Battery')
    
    # Show maximum available solar
    ax7.plot(hours, original_solar_week, 'r-', linewidth=2, label='Max Solar Available')
    
    # Highlight potential clipping (when available > used)
    solar_clipped = original_solar_week - total_solar_used
    clipping_mask = solar_clipped > 0.1  # Threshold for meaningful clipping
    
    if np.any(clipping_mask):
        clipped_hours = np.where(clipping_mask)[0]
        clipped_amounts = solar_clipped[clipping_mask]
        ax7.scatter(clipped_hours, original_solar_week[clipping_mask], 
                   c='red', s=50, alpha=0.8, marker='x', label='Clipped Solar')
        
        # Fill clipped area
        ax7.fill_between(hours, total_solar_used, original_solar_week, 
                        where=(solar_clipped > 0.1), alpha=0.3, color='red', 
                        label='Clipped Energy')
    
    ax7.set_title('Solar Generation & Clipping Analysis', fontweight='bold')
    ax7.set_ylabel('Solar Power (kW)')
    ax7.set_xlabel('Hours')
    ax7.legend()
    ax7.grid(True, alpha=0.3)
    
    # Add summary statistics
    total_available = np.sum(original_solar_week)
    total_used = np.sum(total_solar_used)
    total_clipped = np.sum(solar_clipped[solar_clipped > 0])
    clipping_pct = (total_clipped / total_available * 100) if total_available > 0 else 0
    
    stats_text = f'Week Solar Summary:\nAvailable: {total_available:.1f} kWh\nUsed: {total_used:.1f} kWh\nClipped: {total_clipped:.1f} kWh ({clipping_pct:.1f}%)'
    ax7.text(0.02, 0.98, stats_text, transform=ax7.transAxes, fontsize=9, 
            verticalalignment='top', bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.8))
    
    # 8. Peak Hour Load Coverage Analysis
    ax8 = axes[3, 1]
    
    # Identify peak hours in the week
    peak_mask = dispatch_week['is_peak'][:week_hours]
    peak_hours_list = [h for h in hours if h < len(peak_mask) and peak_mask.iloc[h]]
    
    if peak_hours_list:
        # Get load and battery discharge during peak hours
        peak_loads = [custom_week['load'][h] for h in peak_hours_list]
        peak_battery_discharge = [custom_week['battery_discharge'][h] for h in peak_hours_list]
        peak_grid_usage = [custom_week['grid_usage'][h] for h in peak_hours_list]
        
        # Create stacked bar chart for peak hours
        width = 0.8
        ax8.bar(peak_hours_list, peak_battery_discharge, width, alpha=0.7, 
               color='green', label='Battery Discharge')
        ax8.bar(peak_hours_list, peak_grid_usage, width, bottom=peak_battery_discharge, 
               alpha=0.7, color='red', label='Grid Usage')
        
        # Show total load as line
        ax8.plot(peak_hours_list, peak_loads, 'ko-', linewidth=2, label='Total Load')
        
        # Calculate peak coverage statistics
        total_peak_load = sum(peak_loads)
        total_battery_coverage = sum(peak_battery_discharge)
        battery_coverage_pct = (total_battery_coverage / total_peak_load * 100) if total_peak_load > 0 else 0
        
        ax8.set_title('Peak Hour Load Coverage (4-9 PM)', fontweight='bold')
        ax8.set_ylabel('Power (kW)')
        ax8.set_xlabel('Hours')
        ax8.legend()
        ax8.grid(True, alpha=0.3)
        
        # Add coverage statistics
        coverage_text = f'Peak Coverage:\nBattery: {battery_coverage_pct:.1f}%\nTotal Peak Load: {total_peak_load:.1f} kWh'
        ax8.text(0.02, 0.98, coverage_text, transform=ax8.transAxes, fontsize=9,
                verticalalignment='top', bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.8))
    else:
        ax8.text(0.5, 0.5, 'No peak hours in selected week', 
                transform=ax8.transAxes, ha='center', va='center', fontsize=12)
        ax8.set_title('Peak Hour Load Coverage (4-9 PM)', fontweight='bold')
    
    # 9. Peak Load Predictions Bar Chart
    ax9 = axes[4, 0]
    
    # Get daily prediction data for the week
    battery_capacity = 13.5  # kWh - should match dispatch generator
    max_battery_usable = (80 - 20) / 100 * battery_capacity  # 8.1 kWh usable
    
    days_data = []
    for day in week_days:
        day_start_hour = day * 24
        day_6am = day_start_hour + 6
        day_4pm = day_start_hour + 16
        
        # Only process if these hours are in our week view
        if day_6am < week_hours and day_4pm < week_hours and day_6am < len(dispatch_week):
            # Get prediction data from dispatch log
            pred_data = dispatch_week.iloc[day_6am]
            peak_load_target = pred_data['peak_load_target']
            
            # Calculate battery capacities
            soc_6am = custom_week['battery_soc'][day_6am] if day_6am < len(custom_week['battery_soc']) else 50
            soc_4pm = custom_week['battery_soc'][day_4pm] if day_4pm < len(custom_week['battery_soc']) else 50
            
            battery_6am_kwh = soc_6am / 100 * battery_capacity
            battery_4pm_kwh = soc_4pm / 100 * battery_capacity
            
            # Available energy (above 20% SOC)
            available_6am = max(0, battery_6am_kwh - (20 / 100 * battery_capacity))
            available_4pm = max(0, battery_4pm_kwh - (20 / 100 * battery_capacity))
            
            # Target energy needed for peak (limited by battery capacity)
            peak_target_kwh = min(peak_load_target, max_battery_usable)
            
            days_data.append({
                'day': day + 1,
                'peak_target': peak_target_kwh,
                'available_6am': available_6am,
                'available_4pm': available_4pm,
                'shortfall_6am': max(0, peak_target_kwh - available_6am),
                'shortfall_4pm': max(0, peak_target_kwh - available_4pm)
            })
    
    if days_data:
        days = [d['day'] for d in days_data]
        x_pos = np.arange(len(days))
        width = 0.35
        
        # 6 AM bars (morning assessment)
        available_6am = [d['available_6am'] for d in days_data]
        shortfall_6am = [d['shortfall_6am'] for d in days_data]
        
        ax9.bar(x_pos - width/2, available_6am, width, alpha=0.7, color='lightblue', label='Available at 6 AM')
        ax9.bar(x_pos - width/2, shortfall_6am, width, bottom=available_6am, alpha=0.7, color='lightcoral', label='Shortfall at 6 AM')
        
        # 4 PM bars (pre-peak assessment)  
        available_4pm = [d['available_4pm'] for d in days_data]
        shortfall_4pm = [d['shortfall_4pm'] for d in days_data]
        
        ax9.bar(x_pos + width/2, available_4pm, width, alpha=0.7, color='darkblue', label='Available at 4 PM')
        ax9.bar(x_pos + width/2, shortfall_4pm, width, bottom=available_4pm, alpha=0.7, color='darkred', label='Shortfall at 4 PM')
        
        # Add target lines
        peak_targets = [d['peak_target'] for d in days_data]
        for i, target in enumerate(peak_targets):
            ax9.plot([i - width/2 - 0.1, i + width/2 + 0.1], [target, target], 'g-', linewidth=2, alpha=0.8)
        
        # Formatting
        ax9.set_xlabel('Day')
        ax9.set_ylabel('Energy (kWh)')
        ax9.set_title('Peak Load Predictions: Battery Readiness vs Target', fontweight='bold')
        ax9.set_xticks(x_pos)
        ax9.set_xticklabels([f'Day {d}' for d in days])
        ax9.legend()
        ax9.grid(True, alpha=0.3, axis='y')
        
        # Add statistics text
        total_target = sum(peak_targets)
        total_available_4pm = sum(available_4pm)
        avg_coverage = (total_available_4pm / total_target * 100) if total_target > 0 else 0
        
        well_prepared = sum(1 for d in days_data if d['shortfall_4pm'] < 0.5)  # Less than 0.5 kWh shortfall
        
        stats_text = f'Week Summary:\nAvg Coverage: {avg_coverage:.1f}%\nWell-Prepared: {well_prepared}/{len(days)} days'
        ax9.text(0.02, 0.98, stats_text, transform=ax9.transAxes, fontsize=9,
                verticalalignment='top', bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.8))
    else:
        ax9.text(0.5, 0.5, 'No prediction data available', 
                transform=ax9.transAxes, ha='center', va='center', fontsize=12)
        ax9.set_title('Peak Load Predictions: Battery Readiness vs Target', fontweight='bold')
    
    # 10. Daily Energy Balance
    ax10 = axes[4, 1]
    
    if days_data:
        # Calculate daily energy flows
        daily_energy = []
        for day in week_days:
            day_start = day * 24
            day_end = min((day + 1) * 24, week_hours)
            
            if day_end > day_start:
                day_hours = range(day_start, day_end)
                day_solar = sum(custom_week['solar'][h] for h in day_hours if h < len(custom_week['solar']))
                day_load = sum(custom_week['load'][h] for h in day_hours if h < len(custom_week['load']))
                day_grid = sum(custom_week['grid_usage'][h] for h in day_hours if h < len(custom_week['grid_usage']))
                
                daily_energy.append({
                    'day': day + 1,
                    'solar': day_solar,
                    'load': day_load,
                    'grid': day_grid,
                    'solar_fraction': (day_solar / day_load * 100) if day_load > 0 else 0
                })
        
        if daily_energy:
            days = [d['day'] for d in daily_energy]
            solar_fractions = [d['solar_fraction'] for d in daily_energy]
            
            bars = ax10.bar(days, solar_fractions, alpha=0.7, color='gold')
            
            # Color code bars by performance
            for i, (bar, fraction) in enumerate(zip(bars, solar_fractions)):
                if fraction >= 70:
                    bar.set_color('green')
                elif fraction >= 40:
                    bar.set_color('orange')
                else:
                    bar.set_color('red')
            
            ax10.axhline(y=50, color='blue', linestyle='--', alpha=0.7, label='50% Target')
            ax10.set_xlabel('Day')
            ax10.set_ylabel('Solar Fraction (%)')
            ax10.set_title('Daily Solar Energy Fraction', fontweight='bold')
            ax10.set_ylim(0, 100)
            ax10.legend()
            ax10.grid(True, alpha=0.3, axis='y')
    else:
        ax10.text(0.5, 0.5, 'No energy data available', 
                 transform=ax10.transAxes, ha='center', va='center', fontsize=12)
        ax10.set_title('Daily Solar Energy Fraction', fontweight='bold')
    
    plt.tight_layout()
    plt.show()


def plot_annual_soc_violations(dispatch_log):
    """
    Create a separate figure showing SOC violations across the full year
    """
    if dispatch_log is None or len(dispatch_log) == 0:
        print("No dispatch log available for SOC violation analysis")
        return
    
    print("📊 Generating annual SOC violation analysis...")
    
    # Create figure for annual analysis
    fig, axes = plt.subplots(3, 1, figsize=(16, 12))
    fig.suptitle('Annual Battery SOC Analysis: Violations & Performance', fontsize=16, fontweight='bold')
    
    # Convert hour index to day of year
    hours = len(dispatch_log)
    days = [h // 24 for h in range(hours)]
    unique_days = sorted(set(days))
    
    # 1. Daily Minimum SOC
    ax1 = axes[0]
    daily_min_soc = []
    daily_max_soc = []
    violation_days = []
    critical_days = []
    
    for day in unique_days:
        day_start = day * 24
        day_end = min((day + 1) * 24, hours)
        day_data = dispatch_log.iloc[day_start:day_end]
        
        if len(day_data) > 0:
            min_soc = day_data['soc'].min()
            max_soc = day_data['soc'].max()
            daily_min_soc.append(min_soc)
            daily_max_soc.append(max_soc)
            
            # Track violation days
            if min_soc < 15.0:
                violation_days.append(day)
            if min_soc < 10.0:
                critical_days.append(day)
        else:
            daily_min_soc.append(50.0)
            daily_max_soc.append(50.0)
    
    # Plot daily SOC range
    ax1.fill_between(unique_days, daily_min_soc, daily_max_soc, alpha=0.3, color='blue', label='Daily SOC Range')
    ax1.plot(unique_days, daily_min_soc, 'b-', linewidth=1, label='Daily Minimum SOC')
    
    # Mark violation days
    if violation_days:
        violation_min_soc = [daily_min_soc[day] for day in violation_days]
        ax1.scatter(violation_days, violation_min_soc, c='orange', s=30, alpha=0.8, label=f'Low SOC Days (<15%): {len(violation_days)}')
    
    if critical_days:
        critical_min_soc = [daily_min_soc[day] for day in critical_days]
        ax1.scatter(critical_days, critical_min_soc, c='red', s=50, alpha=0.9, label=f'Critical SOC Days (<10%): {len(critical_days)}')
    
    # Reference lines
    ax1.axhline(y=20, color='red', linestyle='--', alpha=0.7, label='Target Min SOC (20%)')
    ax1.axhline(y=15, color='orange', linestyle='--', alpha=0.5, label='Warning Level (15%)')
    ax1.axhline(y=10, color='red', linestyle='--', alpha=0.5, label='Critical Level (10%)')
    ax1.axhline(y=80, color='green', linestyle='--', alpha=0.7, label='Target Max SOC (80%)')
    
    ax1.set_title('Daily SOC Range & Violations Throughout Year', fontweight='bold')
    ax1.set_ylabel('SOC (%)')
    ax1.set_ylim(0, 100)
    ax1.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    ax1.grid(True, alpha=0.3)
    
    # 2. Monthly Violation Summary
    ax2 = axes[1]
    
    # Group violations by month
    monthly_violations = {month: {'low': 0, 'critical': 0, 'total_days': 0} for month in range(1, 13)}
    
    for day in unique_days:
        # Approximate month (assuming 365-day year)
        month = min(12, ((day * 12) // 365) + 1)
        monthly_violations[month]['total_days'] += 1
        
        if day < len(daily_min_soc):
            if daily_min_soc[day] < 15.0:
                monthly_violations[month]['low'] += 1
            if daily_min_soc[day] < 10.0:
                monthly_violations[month]['critical'] += 1
    
    months = list(monthly_violations.keys())
    low_violations = [monthly_violations[m]['low'] for m in months]
    critical_violations = [monthly_violations[m]['critical'] for m in months]
    
    width = 0.35
    x_pos = np.arange(len(months))
    
    bars1 = ax2.bar(x_pos - width/2, low_violations, width, alpha=0.7, color='orange', label='Low SOC Days (<15%)')
    bars2 = ax2.bar(x_pos + width/2, critical_violations, width, alpha=0.7, color='red', label='Critical SOC Days (<10%)')
    
    ax2.set_title('Monthly SOC Violations', fontweight='bold')
    ax2.set_xlabel('Month')
    ax2.set_ylabel('Number of Days')
    ax2.set_xticks(x_pos)
    ax2.set_xticklabels(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'])
    ax2.legend()
    ax2.grid(True, alpha=0.3, axis='y')
    
    # Add value labels on bars
    for bar, value in zip(bars1, low_violations):
        if value > 0:
            ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1, 
                    str(value), ha='center', va='bottom', fontsize=9)
    
    for bar, value in zip(bars2, critical_violations):
        if value > 0:
            ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1, 
                    str(value), ha='center', va='bottom', fontsize=9)
    
    # 3. SOC Distribution Histogram
    ax3 = axes[2]
    
    all_soc_values = dispatch_log['soc'].values
    
    # Create histogram
    bins = np.arange(0, 101, 5)  # 5% bins
    counts, _, patches = ax3.hist(all_soc_values, bins=bins, alpha=0.7, color='skyblue', edgecolor='black')
    
    # Color code bins by safety level
    for i, patch in enumerate(patches):
        bin_center = (bins[i] + bins[i+1]) / 2
        if bin_center < 10:
            patch.set_facecolor('red')
        elif bin_center < 15:
            patch.set_facecolor('orange')
        elif bin_center < 20:
            patch.set_facecolor('yellow')
        else:
            patch.set_facecolor('lightgreen')
    
    # Add reference lines
    ax3.axvline(x=10, color='red', linestyle='--', alpha=0.8, label='Critical (10%)')
    ax3.axvline(x=15, color='orange', linestyle='--', alpha=0.8, label='Warning (15%)')
    ax3.axvline(x=20, color='green', linestyle='--', alpha=0.8, label='Target Min (20%)')
    ax3.axvline(x=80, color='blue', linestyle='--', alpha=0.8, label='Target Max (80%)')
    
    ax3.set_title('SOC Distribution Throughout Year', fontweight='bold')
    ax3.set_xlabel('State of Charge (%)')
    ax3.set_ylabel('Hours')
    ax3.legend()
    ax3.grid(True, alpha=0.3, axis='y')
    
    # Add statistics text
    stats_text = f'''Annual SOC Statistics:
Min SOC: {all_soc_values.min():.1f}%
Max SOC: {all_soc_values.max():.1f}%
Avg SOC: {all_soc_values.mean():.1f}%
Hours <10%: {sum(1 for x in all_soc_values if x < 10)} ({sum(1 for x in all_soc_values if x < 10)/len(all_soc_values)*100:.1f}%)
Hours <15%: {sum(1 for x in all_soc_values if x < 15)} ({sum(1 for x in all_soc_values if x < 15)/len(all_soc_values)*100:.1f}%)'''
    
    ax3.text(0.98, 0.98, stats_text, transform=ax3.transAxes, fontsize=9,
            verticalalignment='top', horizontalalignment='right',
            bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
    
    plt.tight_layout()
    plt.show()
    
    # Print summary
    print(f"\n📋 Annual SOC Violation Summary:")
    print("=" * 40)
    print(f"Total violation days (<15% SOC): {len(violation_days)}/{len(unique_days)} ({len(violation_days)/len(unique_days)*100:.1f}%)")
    print(f"Critical violation days (<10% SOC): {len(critical_days)}/{len(unique_days)} ({len(critical_days)/len(unique_days)*100:.1f}%)")
    print(f"Worst month: {max(monthly_violations.keys(), key=lambda m: monthly_violations[m]['low'])} ({monthly_violations[max(monthly_violations.keys(), key=lambda m: monthly_violations[m]['low'])]['low']} days)")
    
    if critical_days:
        print(f"\n🚨 Critical violation days: {critical_days[:10]}{'...' if len(critical_days) > 10 else ''}")
    
    return {
        'violation_days': violation_days,
        'critical_days': critical_days,
        'monthly_violations': monthly_violations,
        'daily_min_soc': daily_min_soc
    }


def main():
    """
    Main execution function to run the custom dispatch demo
    """
    # Configure matplotlib for interactive display
    plt.style.use('default')
    plt.rcParams['figure.figsize'] = (14, 8)
    plt.rcParams['font.size'] = 10
    
    # Load existing data
    county_name = "alameda"
    sam_file = f"data/loadprofiles/baseline/single-family-detached/{county_name}/sam_optimized_load_profiles_{county_name}.csv"
    weather_file = f"data/loadprofiles/baseline/single-family-detached/{county_name}/weather_TMY_{county_name}.csv"
    load_file = f"data/loadprofiles/baseline/single-family-detached/{county_name}/combined_profiles_baseline_{county_name}.csv"
    
    print("SAM Custom Dispatch Demo")
    print("=" * 30)
    
    # Load reference data
    reference_sam_data = None
    if os.path.exists(sam_file):
        reference_sam_data = pd.read_csv(sam_file, index_col=0, parse_dates=True)
        print(f"✓ Loaded reference SAM data for {county_name}")
    else:
        print(f"⚠ Reference SAM data not found: {sam_file}")
    
    # Load load profile
    load_profile = None
    if os.path.exists(load_file):
        load_data = pd.read_csv(load_file)
        load_profile = load_data["electricity.real_and_simulated.for_typical_county_home.kwh"].tolist()
        annual_load_kwh = sum(load_profile)
        print(f"✓ Loaded load profile: {len(load_profile)} hours, {annual_load_kwh:.0f} kWh/year")
    else:
        print(f"⚠ Load file not found: {load_file}")
        return
    
    # Check weather file
    if not os.path.exists(weather_file):
        print(f"⚠ Weather file not found: {weather_file}")
        return
    else:
        print(f"✓ Weather file found")
    
    # Initialize dispatch generator
    pge_rate_plan = PGE_RATE_PLANS["E-TOU-C"]
    dispatch_generator = CustomDispatchScheduleGenerator(pge_rate_plan)
    
    print(f"\n✓ Custom dispatch generator initialized:")
    print(f"  Battery capacity: {dispatch_generator.battery_capacity} kWh")
    print(f"  Cycle cost threshold: ${dispatch_generator.cycle_cost:.3f}/kWh")
    print(f"  SOC operating range: {dispatch_generator.min_soc}% - {dispatch_generator.max_soc}%")
    
    # Get solar profile
    if reference_sam_data is not None:
        solar_profile = reference_sam_data['System to Load'].tolist()
        print(f"✓ Using solar profile from reference SAM data")
    else:
        # Create simple solar profile for demo
        solar_profile = []
        for h in range(8760):
            hour_of_day = h % 24
            if 6 <= hour_of_day <= 18:
                solar_intensity = np.sin((hour_of_day - 6) * np.pi / 12) * 3.0
                solar_profile.append(max(0, solar_intensity))
            else:
                solar_profile.append(0.0)
        print(f"⚠ Using synthetic solar profile for demo")
    
    # Generate custom dispatch schedules
    print("\n🔄 Generating custom dispatch schedules...")
    charge_schedule, discharge_schedule, gridcharge_schedule = dispatch_generator.generate_custom_dispatch_schedule(
        load_profile, solar_profile
    )
    
    # Analyze the strategy
    print("\n📊 Analyzing dispatch strategy...")
    analysis = dispatch_generator.analyze_dispatch_strategy()
    
    # Run SAM with custom dispatch
    print("\n🚀 Running SAM simulation with custom dispatch...")
    custom_sam_results = run_sam_with_custom_dispatch(
        weather_file, load_profile, charge_schedule, discharge_schedule, gridcharge_schedule
    )
    
    if custom_sam_results is None:
        print("❌ SAM simulation failed")
        return
    
    # Compare results
    if reference_sam_data is not None:
        print("\n⚖️ Comparing results...")
        comparison_results = compare_dispatch_results(
            reference_sam_data, 
            custom_sam_results, 
            dispatch_generator.dispatch_log
        )
    
    # Economic analysis
    print("\n💰 Calculating economic benefits...")
    economic_analysis = calculate_economic_benefits(
        custom_sam_results,
        reference_sam_data,
        dispatch_generator.dispatch_log,
        pge_rate_plan
    )
    
    # Generate plots for different time periods
    print("\n📈 Generating visualization plots...")
    
    # Figure 1: First week of January (winter analysis)
    print("  📊 Figure 1: January analysis (first week)...")
    plot_custom_dispatch_analysis(
        custom_sam_results, 
        dispatch_generator.dispatch_log, 
        reference_sam_data,
        month="January",
        week_offset=0  # First week of year
    )
    
    # Figure 2: First week of July (summer analysis) 
    print("  📊 Figure 2: July analysis (mid-summer week)...")
    july_start_day = 31 + 28 + 31 + 30 + 31 + 30  # Jan+Feb+Mar+Apr+May+Jun = 181 days
    plot_custom_dispatch_analysis(
        custom_sam_results, 
        dispatch_generator.dispatch_log, 
        reference_sam_data,
        month="July", 
        week_offset=july_start_day + 7  # Second week of July for better summer representation
    )
    
    # Figure 3: Annual SOC violation analysis
    print("  📊 Figure 3: Annual SOC violation analysis...")
    plot_annual_soc_violations(dispatch_generator.dispatch_log)
    
    print("\n✅ Custom dispatch demo completed successfully!")
    print("Check the displayed plots for detailed analysis.")


if __name__ == "__main__":
    main()
