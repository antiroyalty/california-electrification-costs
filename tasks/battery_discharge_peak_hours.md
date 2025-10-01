# Battery Discharge During Peak Hours (4-9pm): Research Analysis

## Executive Summary

This research report analyzes potential causes for battery systems not discharging during the critical 4-9pm peak period in California's Time-of-Use (TOU) rate structure. The analysis combines findings from the project's `pvsamv1_battery.py` implementation with comprehensive NREL SAM (System Advisor Model) documentation research.

## Current Implementation Analysis

### Battery Configuration Overview

The project implements a sophisticated battery dispatch system using NREL SAM's PVsamv1 module with the following key configuration:

- **Dispatch Mode**: Manual Dispatch (Mode 3) with period-based scheduling
- **Battery Capacity**: 13.5 kWh (Tesla Powerwall equivalent)
- **Peak Discharge Window**: 6pm-11pm (18:00-23:00) mapped to Period 3
- **Solar Charging Window**: 6am-5pm (06:00-17:00) mapped to Period 2
- **SOC Constraints**: 20% minimum, 80% maximum, 50% initial

### Current Schedule Configuration

From `pvsamv1_battery.py:687-703`:
```python
# Build dynamic schedule based on time windows:
daily_schedule = []
for hour in range(24):
    if solar_start <= hour <= solar_end:        # 6am-5pm
        daily_schedule.append(2)  # Solar charging period
    elif peak_start <= hour <= peak_end:        # 6pm-11pm  
        daily_schedule.append(3)  # Peak discharge period
    else:
        daily_schedule.append(1)  # Off-peak period
```

**Issue Identified**: The current configuration maps peak discharge to 6pm-11pm (18-23), but the target period is 4-9pm (16-21). This **2-hour misalignment** is a primary cause of the discharge issue.

## Root Causes for 4-9pm Discharge Failures

### 1. Schedule Period Misalignment (Critical Issue)

**Problem**: Current configuration:
- Target period: 4-9pm (hours 16-21)
- Configured period: 6pm-11pm (hours 18-23)
- **Gap**: Hours 16-17 (4-6pm) are not covered by discharge period

**Solution**: Update constants in `pvsamv1_battery.py:70-71`:
```python
PEAK_DISCHARGE_START_HOUR = 16      # Change from 18 to 16
PEAK_DISCHARGE_END_HOUR = 21        # Change from 23 to 21
```

### 2. Insufficient State of Charge (SOC)

**Analysis**: The battery may not reach adequate charge levels by 4pm to serve the peak period.

**Current Pre-charging Logic** (`pvsamv1_battery.py:196-222`):
- Calculates required energy for 4-9pm peak period
- Accounts for round-trip efficiency losses (90%)
- Determines target SOC needed by 4pm
- Uses both solar charging (6am-5pm) and grid backup charging (10am-4pm)

**Potential Issues**:
- Insufficient solar generation on cloudy days
- High pre-peak load consuming stored energy
- Conservative maximum SOC limit (80% vs. typical 95%)

### 3. Configuration Flag Conflicts

**Critical Flags That Can Block Discharge**:

From `pvsamv1_battery.py:728-734`:
```python
# Smart discharge - only discharge when load exceeds solar
batt_dispatch_discharge_only_load_exceeds_system = 0    # Currently disabled
```

**Potential Problem**: If this flag is inadvertently set to `1`, the battery will only discharge when load exceeds solar generation. During late afternoon (4-6pm), significant solar generation may still exist, preventing discharge.

**Grid Export Prevention** (`pvsamv1_battery.py:742`):
```python
batt_dispatch_auto_btm_can_discharge_to_grid = 0    # Correctly disabled
```

### 4. Power and Rate Limitations

**Discharge Rate Constraints**:
- Maximum AC discharge: 5.0 kW (typical Powerwall limit)
- DC-DC efficiency: 96%
- If peak load exceeds 5kW, grid supplementation is required regardless

**Battery Degradation**: Over time, actual discharge capacity may be less than nameplate rating.

### 5. Load Profile Dependencies

**Proportional Discharge Logic** (`pvsamv1_battery.py:1087-1121`):
The system calculates discharge proportional to load patterns. If loads during 4-6pm are significantly lower than 6-9pm, the current period mapping (6-11pm) may better match the actual load profile.

## Diagnostic Recommendations

### Immediate Actions

1. **Fix Period Mapping**:
   ```python
   PEAK_DISCHARGE_START_HOUR = 16  # 4pm start
   PEAK_DISCHARGE_END_HOUR = 21    # 9pm end
   ```

2. **Verify Discharge Schedule Output**:
   Run `print_first_24h_dispatch_table()` to confirm hours 16-20 show non-zero discharge percentages.

3. **Check SOC at 4pm**:
   Monitor `batt_SOC` output at hour 16 to ensure adequate charge (>30% for meaningful discharge).

### Detailed Diagnostics

1. **Load Profile Analysis**:
   ```python
   # Check if significant load exists during 4-9pm
   peak_loads = load_forecast[16:21]  # Hours 16-20
   print(f"Peak period loads (4-9pm): {peak_loads}")
   ```

2. **Solar Generation Overlap**:
   ```python
   # Verify solar generation during early peak hours
   solar_4_to_6pm = solar_forecast[16:18] if solar_forecast else [0, 0]
   print(f"Solar at 4-6pm: {solar_4_to_6pm}")
   ```

3. **Dispatch Schedule Validation**:
   ```python
   # Confirm non-zero discharge during target hours
   discharge_4_to_9pm = discharge_schedule['dispatch_manual_percent_discharge'][16:21]
   print(f"Scheduled discharge 4-9pm: {discharge_4_to_9pm}")
   ```

## Advanced Configuration Options

### Enhanced Discharge Strategy

Consider implementing a **hybrid approach**:

1. **Early Peak (4-6pm)**: Lower discharge rate to preserve battery for higher evening loads
2. **Prime Peak (6-9pm)**: Maximum discharge rate when TOU rates are highest

### Dynamic SOC Management

Implement **variable SOC targets** based on:
- Day-ahead load forecasts
- Weather predictions
- Historical peak usage patterns

### Grid Charging Optimization

Current grid charging window (10am-4pm) may be insufficient. Consider:
- Earlier grid charging start (8am) during high-demand seasons
- Dynamic charging rates based on afternoon load predictions

## SAM Parameter Reference

### Key Manual Dispatch Parameters

| Parameter | Current Value | Recommended | Purpose |
|-----------|---------------|-------------|---------|
| `batt_dispatch_choice` | 3 | 3 | Manual dispatch mode |
| `dispatch_manual_sched` | [1,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,3,3,3,3,3,1] | [1,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,3,3,3,3,3,1,1,1] | Hour-to-period mapping |
| `dispatch_manual_percent_discharge` | [0,0,discharge_max,0,0,0] | [0,0,discharge_max,0,0,0] | Discharge % by period |
| `batt_minimum_SOC` | 20 | 20 | Minimum discharge limit |
| `batt_maximum_SOC` | 80 | 85-90 | Maximum charge limit |

### Critical Control Flags

| Flag | Current | Impact if Wrong |
|------|---------|-----------------|
| `dispatch_manual_system_charge_first` | 1 | 0 = No solar priority |
| `batt_dispatch_auto_can_charge` | 1 | 0 = No charging |
| `batt_dispatch_discharge_only_load_exceeds_system` | 0 | 1 = No discharge when solar > load |
| `batt_dispatch_auto_can_gridcharge` | 1 | 0 = No grid charging |

## Conclusion

The primary cause of batteries not discharging during 4-9pm appears to be **schedule period misalignment**. The current configuration targets 6-11pm instead of the intended 4-9pm window. This 2-hour shift means the first two hours of the peak period (4-6pm) are not covered by the discharge schedule.

### Immediate Fix

Update `PEAK_DISCHARGE_START_HOUR` from 18 to 16 and `PEAK_DISCHARGE_END_HOUR` from 23 to 21 in `pvsamv1_battery.py`.

### Validation Steps

1. Verify schedule mapping shows periods 2→3 transition at hour 16
2. Confirm non-zero discharge percentages for hours 16-20
3. Monitor SOC levels ensure adequate charge by 4pm
4. Test with actual load profiles to validate discharge behavior

This configuration change should resolve the primary discharge timing issue while maintaining the sophisticated predictive scheduling and efficiency optimization already implemented in the system.