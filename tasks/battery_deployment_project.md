# Battery Deployment Strategy Project Plan

## Overview
Based on analysis of `tasks/research.md` and `pvsamv1_battery.py`, this plan outlines the logic changes needed to optimize battery operation for California's time-of-use (TOU) rates. The goal is to implement predictive charging that looks ahead to calculate energy needs for the 4-9pm peak period, prioritize solar charging with grid backup, and ensure aggressive discharge during peak hours.

## Current State Analysis

### Refactored Implementation (`pvsamv1_battery.py`)
- **Architecture**: Clean dataclass-based design with clear separation of concerns
- **Configuration**: Environment-driven with `SimulationConfiguration` dataclass
- **Runtime Overrides**: `RuntimeOverrides` dataclass for env-based parameter control
- **Module Management**: Streamlined `SamModules` and `SamPresetFiles` structures
- **Validation**: Strict validation of required weather and load CSV files
- **Output Collection**: Structured `SimulationSeries` dataclass for all energy flows
- **Reporting**: Modular reporting system with configurable visualization

### Enhanced Features Available
- **Environment Variables**: Support for runtime configuration via env vars
- **SOC Control**: Runtime overrides for `MIN_SOC`, `MAX_SOC`, `INITIAL_SOC`
- **Dispatch Control**: `DISPATCH_MODE` override capability
- **Grid Control**: `CAN_EXPORT_TO_GRID`, `GRID_INTERCONNECTION_LIMIT_KWAC` overrides
- **Data Validation**: Strict 8760-hour validation for load profiles
- **Structured Outputs**: Clean extraction of all energy flow components

## Required Logic Changes

### 1. Predictive Peak Energy Calculation

#### Current Issue
- No lookahead to determine required battery energy for upcoming peak periods
- Battery charging is reactive rather than predictive
- No consideration of round-trip efficiency losses in charging strategy

#### Required Changes
```python
def calculate_peak_energy_requirements(load_forecast, day_index, battery_efficiency=0.90):
    """Calculate energy needed for 4-9pm peak period including efficiency losses"""
    
    # Peak period hours (4-9pm = hours 16-20)
    peak_start = 16
    peak_end = 21
    
    # Get load forecast for peak period
    peak_load_kwh = 0.0
    for hour in range(peak_start, peak_end):
        hour_index = day_index * 24 + hour
        if hour_index < len(load_forecast):
            peak_load_kwh += load_forecast[hour_index]
    
    # Account for round-trip efficiency losses
    # Energy needed to store = peak_load / efficiency
    energy_to_store_kwh = peak_load_kwh / battery_efficiency
    
    return {
        'peak_load_kwh': peak_load_kwh,
        'energy_to_store_kwh': energy_to_store_kwh,
        'efficiency_loss_kwh': energy_to_store_kwh - peak_load_kwh
    }

def calculate_precharge_target_soc(peak_energy_req, battery_capacity_kwh, min_soc=20.0):
    """Calculate target SOC needed by 4pm to serve peak load"""
    
    # Energy available at minimum SOC
    min_energy_kwh = (min_soc / 100.0) * battery_capacity_kwh
    
    # Total energy needed = minimum energy + peak energy requirement
    target_energy_kwh = min_energy_kwh + peak_energy_req['energy_to_store_kwh']
    
    # Convert to SOC percentage
    target_soc = min(90.0, (target_energy_kwh / battery_capacity_kwh) * 100.0)
    
    return {
        'target_soc': target_soc,
        'target_energy_kwh': target_energy_kwh,
        'precharge_energy_kwh': peak_energy_req['energy_to_store_kwh']
    }
```

### 2. Solar-Priority with Grid Backup Charging Logic

#### Updated Strategy
- **Primary**: Charge from excess solar generation
- **Secondary**: Use grid charging to meet precharge target if solar insufficient
- **Constraint**: Only charge enough to meet calculated peak period requirements

#### Required Changes
```python
def calculate_daily_charging_schedule(day_index, load_forecast, solar_forecast, 
                                    battery_capacity_kwh=13.5, battery_efficiency=0.90):
    """Calculate optimal charging schedule for one day with solar priority + grid backup"""
    
    # Calculate peak energy requirements
    peak_req = calculate_peak_energy_requirements(load_forecast, day_index, battery_efficiency)
    target_info = calculate_precharge_target_soc(peak_req, battery_capacity_kwh)
    
    charging_schedule = [0.0] * 24  # kW charging rate for each hour
    grid_charging_schedule = [0.0] * 24  # kW grid charging rate
    
    # Track cumulative energy stored throughout day
    cumulative_stored_kwh = 0.0
    
    for hour in range(16):  # Charge until 4pm (hour 16)
        hour_index = day_index * 24 + hour
        
        # Available solar after serving load
        solar_gen = solar_forecast[hour_index] if hour_index < len(solar_forecast) else 0
        load = load_forecast[hour_index] if hour_index < len(load_forecast) else 0
        excess_solar = max(0, solar_gen - load)
        
        # Remaining energy needed to meet target
        energy_needed = target_info['precharge_energy_kwh'] - cumulative_stored_kwh
        
        if energy_needed > 0:
            # First priority: charge from solar
            solar_charge_kw = min(excess_solar, energy_needed, MAX_CHARGE_RATE)
            charging_schedule[hour] = solar_charge_kw
            cumulative_stored_kwh += solar_charge_kw
            
            # Second priority: grid charging if still need more energy
            remaining_need = energy_needed - solar_charge_kw
            if remaining_need > 0 and hour >= 10:  # Only grid charge after 10am
                grid_charge_kw = min(remaining_need, MAX_CHARGE_RATE - solar_charge_kw)
                grid_charging_schedule[hour] = grid_charge_kw
                cumulative_stored_kwh += grid_charge_kw
    
    return {
        'solar_charging': charging_schedule,
        'grid_charging': grid_charging_schedule,
        'target_soc': target_info['target_soc'],
        'peak_energy_req': peak_req
    }
```

#### Implementation Location
- Modify JSON configuration in `SAM_Detailed_PV_Battery/`
- Update `dispatch_manual_percent_gridcharge` array
- Adjust `dispatch_manual_sched` to coordinate with solar availability

### 3. Peak Period Discharge Logic (4-9pm)

#### Strategy
- Use preloaded battery energy to serve load during expensive peak hours
- Discharge at calculated rate to reach minimum SOC by 9pm
- Prioritize battery discharge over grid consumption during 4-9pm

#### Required Changes
```python
def calculate_peak_discharge_schedule(target_soc_at_4pm, min_soc=20.0, 
                                    battery_capacity_kwh=13.5, peak_load_forecast=None):
    """Calculate discharge schedule to efficiently use preloaded energy during 4-9pm"""
    
    discharge_schedule = [0.0] * 8760  # kW discharge rate
    discharge_percent = [0.0] * 8760   # Percent discharge per hour
    
    for day in range(365):
        peak_start = 16  # 4pm
        peak_end = 21    # 9pm
        
        # Energy available for discharge (above minimum SOC)
        available_energy_kwh = ((target_soc_at_4pm - min_soc) / 100.0) * battery_capacity_kwh
        
        # Distribute discharge over 5-hour peak period
        if peak_load_forecast:
            # Smart discharge based on load profile
            peak_hours_load = []
            for hour in range(peak_start, peak_end):
                hour_index = day * 24 + hour
                if hour_index < len(peak_load_forecast):
                    peak_hours_load.append(peak_load_forecast[hour_index])
                else:
                    peak_hours_load.append(0.0)
            
            # Proportional discharge based on load profile
            total_peak_load = sum(peak_hours_load)
            if total_peak_load > 0:
                for i, hour in enumerate(range(peak_start, peak_end)):
                    hour_index = day * 24 + hour
                    load_fraction = peak_hours_load[i] / total_peak_load
                    discharge_kwh = min(available_energy_kwh * load_fraction, peak_hours_load[i])
                    discharge_schedule[hour_index] = discharge_kwh
        else:
            # Uniform discharge over peak period
            uniform_discharge_kwh = available_energy_kwh / 5.0  # 5 hours
            for hour in range(peak_start, peak_end):
                hour_index = day * 24 + hour
                discharge_schedule[hour_index] = uniform_discharge_kwh
    
    return discharge_schedule
```

### 4. Comprehensive Predictive Dispatch Controller

#### Master Algorithm Integration
```python
def create_annual_battery_dispatch_schedule(load_forecast, solar_forecast, 
                                          battery_capacity_kwh=13.5, 
                                          battery_efficiency=0.90,
                                          min_soc=20.0, max_soc=90.0):
    """Master function to create full annual battery dispatch schedule"""
    
    # Initialize annual schedules
    charging_schedule = [0.0] * 8760      # Solar charging kW
    grid_charging_schedule = [0.0] * 8760  # Grid charging kW (when needed)
    discharge_schedule = [0.0] * 8760     # Discharge kW during peak
    target_soc_schedule = [50.0] * 8760   # Target SOC throughout year
    
    for day in range(365):
        # Calculate peak energy requirements for this day
        peak_req = calculate_peak_energy_requirements(load_forecast, day, battery_efficiency)
        
        # Calculate target SOC needed by 4pm
        target_info = calculate_precharge_target_soc(peak_req, battery_capacity_kwh, min_soc)
        
        # Generate charging schedule (solar priority + grid backup)
        daily_charging = calculate_daily_charging_schedule(
            day, load_forecast, solar_forecast, battery_capacity_kwh, battery_efficiency
        )
        
        # Generate discharge schedule for peak period
        daily_discharge = calculate_peak_discharge_schedule(
            target_info['target_soc'], min_soc, battery_capacity_kwh, load_forecast
        )
        
        # Update annual schedules
        day_start = day * 24
        day_end = day_start + 24
        
        charging_schedule[day_start:day_end] = daily_charging['solar_charging']
        grid_charging_schedule[day_start:day_end] = daily_charging['grid_charging']
        discharge_schedule[day_start:day_end] = daily_discharge[day_start:day_end]
        
        # Set target SOC for 4pm each day
        target_soc_schedule[day_start + 16] = target_info['target_soc']
    
    return {
        'solar_charging_kw': charging_schedule,
        'grid_charging_kw': grid_charging_schedule,
        'peak_discharge_kw': discharge_schedule,
        'target_soc_percent': target_soc_schedule,
        'efficiency_losses_kwh_annual': sum([
            calculate_peak_energy_requirements(load_forecast, d, battery_efficiency)['efficiency_loss_kwh'] 
            for d in range(365)
        ])
    }

def validate_dispatch_schedule(dispatch_results, load_forecast):
    """Validate the dispatch schedule meets requirements"""
    
    # Check 1: Grid charging only when solar insufficient
    total_grid_charging = sum(dispatch_results['grid_charging_kw'])
    total_solar_charging = sum(dispatch_results['solar_charging_kw'])
    
    print(f"Annual solar charging: {total_solar_charging:.1f} kWh")
    print(f"Annual grid charging: {total_grid_charging:.1f} kWh")
    print(f"Grid charging percentage: {(total_grid_charging/(total_grid_charging+total_solar_charging)*100):.1f}%")
    
    # Check 2: Efficiency losses accounted for
    print(f"Annual efficiency losses: {dispatch_results['efficiency_losses_kwh_annual']:.1f} kWh")
    
    # Check 3: Peak period coverage
    peak_periods_covered = 0
    for day in range(365):
        day_start = day * 24
        peak_discharge = sum(dispatch_results['peak_discharge_kw'][day_start+16:day_start+21])
        peak_load = sum(load_forecast[day_start+16:day_start+21])
        
        if peak_discharge >= peak_load * 0.8:  # 80% coverage threshold
            peak_periods_covered += 1
    
    coverage_percentage = (peak_periods_covered / 365) * 100
    print(f"Peak period coverage: {coverage_percentage:.1f}% of days")
    
    return {
        'grid_charging_percentage': total_grid_charging/(total_grid_charging+total_solar_charging)*100,
        'peak_coverage_percentage': coverage_percentage,
        'annual_efficiency_losses': dispatch_results['efficiency_losses_kwh_annual']
    }
```

## Implementation Strategy

### Phase 1: Extend Refactored Architecture
1. **Add new dataclasses** for predictive dispatch components:
   - `PredictiveDispatchConfig` for algorithm parameters
   - `PeakEnergyRequirements` for daily calculations
   - `DispatchSchedule` for annual 8760-hour schedules
2. **Create predictive modules** following existing patterns:
   - `predictive_dispatch.py` module with calculation functions
   - `dispatch_validation.py` module for performance verification
3. **Leverage environment variables** for predictive dispatch configuration

### Phase 2: Integration with Existing Structure
1. **Extend `RuntimeOverrides`** to include predictive dispatch parameters
2. **Enhance `configure_modules()`** to apply predictive dispatch schedules
3. **Update `attach_resources()`** to include solar forecasting data
4. **Extend `SimulationSeries`** to capture predictive dispatch metrics
5. **Enhance reporting** to show precharge targets and efficiency metrics

### Phase 3: Production Pipeline Integration
1. **Create wrapper functions** for `step8_run_sam_model_for_solar_storage.py`
2. **Implement batch processing** for all California counties
3. **Add cost analysis** comparing predictive vs baseline dispatch
4. **Generate performance reports** with TOU rate optimization metrics

## Key Configuration Files to Modify

### 1. `SAM_Detailed_PV_Battery/untitled.json`
```json
{
  "dispatch_manual_percent_gridcharge": [calculated_grid_backup_schedule],  // Minimal grid charging when solar insufficient
  "dispatch_manual_sched": [predictive_discharge_schedule],                 // Smart peak discharge
  "dispatch_manual_percent_discharge": [efficiency_adjusted_rates],         // Account for round-trip losses
  "batt_dispatch_auto_btm_can_discharge_to_grid": 0,                       // No grid export
  "batt_load_ac_forecast": [load_forecast_8760],                           // Required for predictive dispatch
  "batt_pv_ac_forecast": [solar_forecast_8760]                             // Required for solar priority logic
}
```

### 2. Integration with Refactored Architecture

#### Extend Existing Dataclasses
Following the established pattern in the refactored code, create new dataclasses for:
- **PredictiveDispatchConfig**: Store algorithm parameters like battery efficiency (0.90), peak hours (4-9pm), SOC bounds
- **PeakEnergyRequirements**: Daily calculations including peak load, energy to store, efficiency losses, target SOC
- **DispatchSchedule**: Annual 8760-hour arrays for solar/grid charging and peak discharge rates

#### Leverage Environment Variable System
Extend the existing environment variable approach to include:
- **BATTERY_EFFICIENCY**: Round-trip efficiency (default 0.90)
- **PEAK_START_HOUR/PEAK_END_HOUR**: Peak period definition (default 16-21)
- **ENABLE_GRID_BACKUP**: Allow minimal grid charging when solar insufficient
- **USE_PREDICTIVE_DISPATCH**: Enable the new dispatch algorithm

#### Enhance RuntimeOverrides Dataclass
Add predictive dispatch fields to the existing `RuntimeOverrides` structure to maintain the clean separation between JSON presets and runtime configuration.

#### Extend Module Configuration Functions
Enhance `configure_modules()` and `apply_runtime_overrides()` to apply predictive dispatch schedules to the SAM model, following the existing pattern of parameter application.

#### Expand SimulationSeries Output
Add new fields to capture predictive dispatch metrics like target SOC achievement, peak coverage percentage, and efficiency loss accounting.

#### Enhance Reporting System
Extend the existing modular reporting to show:
- Daily precharge targets vs actual SOC
- Peak period coverage analysis  
- Solar vs grid charging breakdown
- Efficiency loss impact on operations

## Expected Outcomes

### Battery Operation Profile
- **6am-4pm**: Predictive charging to calculated target SOC (solar priority, grid backup when needed)
- **By 4pm**: Battery preloaded with exact energy needed for 4-9pm period (including efficiency losses)
- **4pm-9pm**: Smart discharge serving peak loads, reaching minimum SOC by 9pm
- **9pm-6am**: Minimal battery operation, serve load from grid

### Economic Benefits
- **Peak shaving**: Reduce expensive 4-9pm grid electricity usage through predictive preloading
- **Efficiency optimization**: Account for round-trip losses in charging strategy
- **Solar maximization**: Prioritize solar while ensuring peak period coverage
- **TOU optimization**: Perfect alignment with California's 4-9pm peak rate periods

### Validation Metrics
1. **Peak coverage**: ≥80% of daily peak load served by battery discharge
2. **Efficiency accounting**: Round-trip losses correctly factored into precharge calculations
3. **Solar priority**: Grid charging only when solar insufficient for target precharge
4. **SOC target achievement**: Battery reaches calculated target SOC by 4pm daily
5. **Minimum SOC compliance**: Battery reaches 20% SOC by 9pm (not depleted)

## Risk Mitigation

### Battery Longevity
- **Respect SOC limits**: Never discharge below 30% minimum
- **Gradual discharge**: Avoid rapid SOC changes that stress battery
- **Temperature considerations**: Account for California climate variations

### System Reliability
- **Backup power**: Maintain 30% SOC for emergency use
- **Load balancing**: Ensure grid can meet load when battery depleted
- **Interconnection limits**: Respect utility grid connection constraints

## Implementation Approach: Building on Refactored Foundation

### Leveraging Existing Architecture
The refactored `pvsamv1_battery.py` provides an excellent foundation for implementing predictive dispatch:

#### Clean Configuration Pipeline
- **SimulationConfiguration**: Extend to include predictive dispatch parameters
- **RuntimeOverrides**: Add fields for efficiency, peak hours, and grid backup settings
- **Environment Variables**: Use existing pattern to configure predictive behavior

#### Modular Design Benefits
- **Separate Concerns**: Create dedicated modules for predictive algorithms
- **Dataclass Pattern**: Follow established structure for new data models
- **Validation System**: Extend existing validation for predictive dispatch requirements
- **Error Handling**: Build on existing exception handling patterns

#### Structured Output Collection
- **SimulationSeries**: Extend to capture predictive dispatch metrics
- **Reporting System**: Enhance existing modular reporting with new visualizations
- **Performance Validation**: Add metrics for target achievement and efficiency tracking

### Key Innovation: Predictive Preloading Algorithm

#### What the Algorithm Does
1. **Daily Energy Forecasting**: Each morning, calculate exact energy needed for that day's 4-9pm peak period
2. **Efficiency Loss Integration**: Account for 90% round-trip efficiency when determining how much to charge
3. **Smart Solar Priority**: Charge first from excess solar, only use grid when solar is insufficient
4. **Target SOC Optimization**: Calculate precise SOC needed by 4pm (not maximum charge)
5. **Peak Period Service**: Discharge stored energy during 4-9pm to minimize grid usage

#### Example Day Calculation
```
Morning forecast shows peak load (4-9pm): 25 kWh
Account for 90% efficiency: 25 ÷ 0.90 = 27.8 kWh needed to store
Target SOC by 4pm: (27.8 kWh ÷ 13.5 kWh capacity) × 100 = ~100% SOC
Solar charging priority: Use excess solar from 6am-4pm first
Grid backup: Only if solar provides <27.8 kWh by 4pm
```

#### Benefits Over Current Approach
- **Precise Energy Management**: No over-charging or under-charging for daily needs
- **Solar Maximization**: Prioritize free solar energy while ensuring peak coverage
- **Cost Optimization**: Minimize expensive peak-hour grid consumption
- **Efficiency Accounting**: Properly factor in battery losses for realistic planning

## Implementation TODO Checklist

### Phase 1: Core Predictive Functions
- [x] **Implement `calculate_peak_energy_requirements()` function** - Added to pvsamv1_battery.py
  - [x] Calculate 4-9pm peak load for given day
  - [x] Account for 90% round-trip efficiency losses
  - [x] Return peak_load_kwh, energy_to_store_kwh, efficiency_loss_kwh
- [x] **Implement `calculate_precharge_target_soc()` function** - Added to pvsamv1_battery.py
  - [x] Calculate target SOC needed by 4pm
  - [x] Account for minimum SOC reserve (20%)
  - [x] Clamp to maximum SOC (90%)
  - [x] Return target_soc, target_energy_kwh, precharge_energy_kwh

### Phase 2: Integration with Existing Architecture
- [ ] **Add predictive dispatch demo to main() function**
  - [ ] Calculate peak requirements for sample day
  - [ ] Show target SOC calculation
  - [ ] Display efficiency loss impact
- [ ] **Extend RuntimeOverrides dataclass**
  - [ ] Add battery_efficiency parameter
  - [ ] Add enable_predictive_dispatch flag
  - [ ] Add peak_start_hour and peak_end_hour parameters
- [ ] **Add environment variable support**
  - [ ] BATTERY_EFFICIENCY (default 0.90)
  - [ ] ENABLE_PREDICTIVE_DISPATCH (default false)
  - [ ] PEAK_START_HOUR (default 16)
  - [ ] PEAK_END_HOUR (default 21)

### Phase 3: Dispatch Schedule Generation
- [ ] **Implement daily charging schedule calculation**
  - [ ] Solar-priority charging logic
  - [ ] Grid backup when solar insufficient
  - [ ] Track cumulative energy stored vs target
- [ ] **Implement peak discharge schedule**
  - [ ] Distribute discharge over 4-9pm period
  - [ ] Reach minimum SOC by 9pm
  - [ ] Proportional to load profile
- [ ] **Create annual dispatch schedule function**
  - [ ] Calculate 365 daily requirements
  - [ ] Generate 8760-hour charging/discharge arrays
  - [ ] Validate against battery constraints

### Phase 4: SAM Integration
- [ ] **Modify JSON configuration application**
  - [ ] Apply calculated dispatch_manual_percent_gridcharge
  - [ ] Apply calculated dispatch_manual_percent_discharge
  - [ ] Update dispatch_manual_sched arrays
- [ ] **Enhance reporting and visualization**
  - [ ] Show daily target SOC vs actual
  - [ ] Plot efficiency losses over time
  - [ ] Display peak coverage metrics
- [ ] **Add validation functions**
  - [ ] Verify peak coverage targets met
  - [ ] Check efficiency loss calculations
  - [ ] Validate SOC constraint compliance

### Phase 5: Production Integration
- [ ] **Create wrapper for step8_run_sam_model_for_solar_storage.py**
  - [ ] Generate predictive dispatch schedules
  - [ ] Apply to SAM model configuration
  - [ ] Maintain backward compatibility
- [ ] **Implement batch processing**
  - [ ] Process all California counties
  - [ ] Compare predictive vs baseline costs
  - [ ] Generate county-level performance reports
- [ ] **Add cost analysis enhancements**
  - [ ] Calculate TOU rate savings
  - [ ] Show efficiency loss costs
  - [ ] Compare dispatch strategies

### Testing and Validation
- [ ] **Create unit tests for core functions**
  - [ ] Test edge cases (zero load, high load)
  - [ ] Validate efficiency calculations
  - [ ] Check SOC boundary conditions
- [ ] **Integration testing**
  - [ ] Test with actual county load profiles
  - [ ] Validate with SAM model execution
  - [ ] Compare with existing dispatch results
- [ ] **Performance validation**
  - [ ] Measure actual peak coverage achieved
  - [ ] Verify efficiency loss accounting
  - [ ] Validate cost savings calculations