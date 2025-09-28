# SAM Pvsamv1 Battery Charge/Discharge Schedule Configuration

## Overview

This document outlines how to supply custom battery charge and discharge schedules to NREL's SAM (System Advisor Model) Pvsamv1 module through PySAM. Based on research of the codebase and SAM documentation, there are multiple approaches to configuring manual battery dispatch.

## Battery Dispatch Modes

SAM's Pvsamv1 module supports several dispatch modes controlled by `batt_dispatch_choice`:

- **0** = Peak Shaving (automatic)
- **1** = Input Grid Target 
- **2** = Input Battery Power (Custom)
- **3** = Manual Dispatch (period-based scheduling) <--- this is the configuration we are seeking
- **4** = Retail Rate Dispatch (automatic)
- **5** = Self Consumption (automatic)

For custom schedules, use **Mode 3 (Manual Dispatch)** or **Mode 2 (Input Battery Power)**.

## Method 1: Manual Dispatch (Period-Based Scheduling)

### Core Parameters

```python
pv.value('batt_dispatch_choice', 3)  # Enable manual dispatch mode
```

### Schedule Matrix Configuration

Define time periods using 12×24 matrices (month × hour):

```python
# Schedule matrices (values 1-6 define periods for each hour)
dispatch_manual_sched = [
    [1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 1, 1, 1, 1, 1],  # Jan
    [1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 1, 1, 1, 1, 1],  # Feb
    # ... 12 rows total (one per month)
]

pv.value('dispatch_manual_sched', dispatch_manual_sched)
pv.value('dispatch_manual_sched_weekend', dispatch_manual_sched)  # Weekend schedule
```

### Period Action Configuration

Define what happens during each period (1-6):

```python
# Discharge percentages for each period (0-100%)
pv.value('dispatch_manual_percent_discharge', [0, 0, 100, 0, 0, 0])

# Grid charging percentages for each period (0-100%)
pv.value('dispatch_manual_percent_gridcharge', [0, 50, 0, 0, 0, 0])

# Behind-the-meter discharge to grid for each period
pv.value('dispatch_manual_btm_discharge_to_grid', [0, 0, 0, 0, 0, 0])
```

### Control Flags

```python
# PV charging has priority over grid charging
pv.value('dispatch_manual_system_charge_first', 1)

# Allow/prevent grid charging
pv.value('batt_dispatch_auto_can_gridcharge', 1)

# Allow PV charging
pv.value('batt_dispatch_auto_can_charge', 1)

# Prevent battery discharge to grid
pv.value('batt_dispatch_auto_btm_can_discharge_to_grid', 0)

# Only charge when PV exceeds load
pv.value('batt_dispatch_charge_only_system_exceeds_load', 1)

# Only discharge when load exceeds PV
pv.value('batt_dispatch_discharge_only_load_exceeds_system', 1)
```

## Solar Charging Control Parameters

SAM provides specific parameters to control when and how the battery charges from the solar system. These parameters are critical for optimizing solar-to-battery energy flows:

### Key Solar Charging Control Flags

```python
# SOLAR CHARGING PRIORITY AND TIMING
pv.value('dispatch_manual_system_charge_first', 1)
# Description: Forces SAM to prioritize solar charging over grid charging
# Values: 0 = grid priority, 1 = solar priority
# Critical for ensuring solar energy fills battery before any grid charging

pv.value('batt_dispatch_auto_can_charge', 1) 
# Description: Master enable/disable for PV charging capability
# Values: 0 = no PV charging allowed, 1 = PV charging enabled
# Must be 1 for any solar charging to occur

pv.value('batt_dispatch_charge_only_system_exceeds_load', 1)
# Description: Only charge battery when solar production > household load
# Values: 0 = charge regardless of load, 1 = charge only when excess solar
# Prevents charging battery when solar is needed for immediate consumption

pv.value('batt_dispatch_auto_can_gridcharge', 0)
# Description: Enable/disable charging from grid
# Values: 0 = solar-only charging, 1 = allow grid charging
# Set to 0 for pure solar charging strategy

# SOLAR CHARGING RATE AND LIMITS
pv.value('batt_dc_dc_efficiency', 96.0)
# Description: DC-DC converter efficiency for solar-to-battery charging
# Values: 0-100 (percentage), typical range 94-98%
# Accounts for power conversion losses during solar charging

pv.value('inverter_efficiency', 96.0)
# Description: Inverter efficiency affecting AC solar charging paths  
# Values: 0-100 (percentage), typical range 94-98%
# Impacts efficiency when solar charges battery through AC coupling
```

### Solar Charging Hours Configuration

#### **Method 1: Period-Based Solar Hours (Recommended)**

Configure specific time periods when solar charging is allowed:

```python
# Define daily solar charging windows
# Hours 0-5: Night (no solar) - Period 1 (no action)
# Hours 6-17: Daylight (solar available) - Period 2 (charging allowed)  
# Hours 18-23: Evening (no solar) - Period 3 (discharge only)

daily_schedule = [1]*6 + [2]*12 + [3]*6  # 24-hour pattern
schedule_matrix = [daily_schedule] * 12   # Apply to all months

pv.value('dispatch_manual_sched', schedule_matrix)
pv.value('dispatch_manual_sched_weekend', schedule_matrix)

# Configure period actions for solar charging
pv.value('dispatch_manual_percent_discharge', [0, 0, 80, 0, 0, 0])      # Period 3: discharge
pv.value('dispatch_manual_percent_gridcharge', [0, 0, 0, 0, 0, 0])      # No grid charging
pv.value('dispatch_manual_btm_discharge_to_grid', [0, 0, 0, 0, 0, 0])   # No grid export

# Critical: Let SAM automatically handle solar charging during Period 2
# The system will charge from solar when available and load is satisfied
```

#### **Method 2: Seasonal Solar Charging Optimization (NOT Recommended)**

Adjust charging hours based on seasonal daylight patterns:

```python
# Winter schedule (shorter days): 7 AM - 5 PM solar window
winter_schedule = [1]*7 + [2]*10 + [3]*7

# Summer schedule (longer days): 5 AM - 7 PM solar window  
summer_schedule = [1]*5 + [2]*14 + [3]*5

# Build seasonal matrix
seasonal_matrix = [
    winter_schedule,  # Jan
    winter_schedule,  # Feb
    [1]*6 + [2]*12 + [3]*6,  # Mar (transition)
    [1]*6 + [2]*12 + [3]*6,  # Apr
    summer_schedule,  # May
    summer_schedule,  # Jun
    summer_schedule,  # Jul
    summer_schedule,  # Aug
    [1]*6 + [2]*12 + [3]*6,  # Sep (transition)
    [1]*6 + [2]*12 + [3]*6,  # Oct
    winter_schedule,  # Nov
    winter_schedule,  # Dec
]

pv.value('dispatch_manual_sched', seasonal_matrix)
```

### Monitoring Solar Charging Performance

Track solar-to-battery energy flows using SAM output variables:

```python
# After simulation, access these arrays to verify solar charging:
system_to_batt = pv.value('system_to_batt')        # AC solar to battery (kW)
system_to_batt_dc = pv.value('system_to_batt_dc')  # DC solar to battery (kW) 
batt_power = pv.value('batt_power')                 # Net battery power (kW)
gen = pv.value('gen')                               # Total solar generation (kW)

# Calculate solar charging efficiency and patterns
total_solar_to_battery = sum(system_to_batt)       # Total kWh from solar
solar_charging_hours = sum(1 for p in system_to_batt if p > 0.1)  # Hours with solar charging
```

## Method 2: Input Battery Power (Direct Arrays)

### Core Parameters

```python
pv.value('batt_dispatch_choice', 2)  # Enable input battery power mode
```

### Direct Power Arrays

Provide 8760-hour arrays with actual power values:

```python
# Charging from PV (kW, 8760 hours)
pv.value('dispatch_manual_charge', pv_charge_schedule)

# Discharging to load (kW, 8760 hours) 
pv.value('dispatch_manual_discharge', discharge_schedule)

# Charging from grid (kW, 8760 hours)
pv.value('dispatch_manual_gridcharge', grid_charge_schedule)
```

### Specifying Solar Charging Hours

To configure when the battery charges specifically from the solar system (rather than grid), use these approaches:

#### **Option A: Time-Based Solar Charging Schedule**

Create an 8760-hour array specifying exact hours for solar charging:

```python
# Example: Charge from solar during daylight hours (6 AM - 6 PM)
pv_charge_schedule = []
for hour in range(8760):
    hour_of_day = hour % 24
    if 6 <= hour_of_day <= 18:  # Daylight hours
        pv_charge_schedule.append(5.0)  # 5 kW charging rate
    else:
        pv_charge_schedule.append(0.0)  # No solar charging at night

pv.value('dispatch_manual_charge', pv_charge_schedule)
```

#### **Option B: Solar Production-Based Charging**

Align charging schedule with solar production curves:

```python
# Base charging on solar irradiance patterns
import numpy as np

pv_charge_schedule = []
for day in range(365):
    for hour in range(24):
        # Peak solar charging during midday (10 AM - 2 PM)
        if 10 <= hour <= 14:
            charge_rate = 6.0  # Maximum charging during peak solar
        elif 8 <= hour <= 16:
            charge_rate = 3.0  # Moderate charging during shoulder hours
        else:
            charge_rate = 0.0  # No solar charging outside daylight
        
        pv_charge_schedule.append(charge_rate)

pv.value('dispatch_manual_charge', pv_charge_schedule)
```

#### **Option C: Conditional Solar Charging**

Use control flags to automatically charge when solar exceeds load:

```python
# Enable automatic solar charging when production > consumption
pv.value('batt_dispatch_charge_only_system_exceeds_load', 0) # Charge the battery NOT only when solar exceeds load
pv.value('dispatch_manual_system_charge_first', 1)  # Prioritize solar over grid
pv.value('batt_dispatch_auto_can_charge', 1)        # Allow PV charging
pv.value('batt_dispatch_auto_can_gridcharge', 0)    # Disable grid charging

# Set minimal manual charge schedule (automatic logic takes over)
pv_charge_schedule = [0.0] * 8760  # Let SAM determine optimal solar charging
pv.value('dispatch_manual_charge', pv_charge_schedule)
```

### Alternative: Custom Dispatch Array

Provide nested arrays for comprehensive control:

```python
# Format: [discharge_array, charge_array, gridcharge_array]
custom_dispatch = [
    discharge_schedule,     # 8760-hour discharge power (kW)
    pv_charge_schedule,     # 8760-hour PV charge power (kW)
    grid_charge_schedule    # 8760-hour grid charge power (kW)
]

pv.value('batt_custom_dispatch', custom_dispatch)
```

## Implementation in compose_battery_charge_schedule()

Based on the current implementation, here's how to apply the generated schedules:

### Current Function Output

```python
dispatch_schedule = compose_battery_charge_schedule(...)

# Returns:
{
    'dispatch_manual_percent_gridcharge': [0.0] * 8760,  # Grid charge percentages
    'dispatch_manual_percent_discharge': [0.0] * 8760,   # Discharge percentages  
    'validation_metrics': {...}
}
```

### Applying to SAM Model

```python
def apply_predictive_dispatch_schedule(pv: Pvsamv1.Pvsamv1, dispatch_schedule: Dict[str, Any]) -> None:
    """Apply the predictive dispatch schedule to the SAM model."""
    
    # Set manual dispatch mode
    pv.value('batt_dispatch_choice', 3)
    
    # Create schedule matrix that activates charging periods (6am-4pm) and discharge periods (4pm-9pm)
    daily_schedule = [1] * 6 + [2] * 10 + [3] * 5 + [1] * 3  # 24-hour pattern
    schedule_matrix = [daily_schedule] * 12  # Same pattern for all months
    
    pv.value('dispatch_manual_sched', schedule_matrix)
    pv.value('dispatch_manual_sched_weekend', schedule_matrix)
    
    # Convert percentage arrays to period-based values
    # Period 1: No action (0% charge/discharge)
    # Period 2: Charging period (use grid charging percentages)  
    # Period 3: Discharge period (use discharge percentages)
    
    # Get max values for each period
    grid_charge_max = max(dispatch_schedule['dispatch_manual_percent_gridcharge'])
    discharge_max = max(dispatch_schedule['dispatch_manual_percent_discharge'])
    
    # Configure period actions
    pv.value('dispatch_manual_percent_discharge', [0, 0, discharge_max, 0, 0, 0])
    pv.value('dispatch_manual_percent_gridcharge', [0, grid_charge_max, 0, 0, 0, 0])
    pv.value('dispatch_manual_btm_discharge_to_grid', [0, 0, 0, 0, 0, 0])
    
    # Set control flags for predictive dispatch
    pv.value('dispatch_manual_system_charge_first', 1)  # PV priority
    pv.value('batt_dispatch_auto_can_gridcharge', 1)    # Allow grid charging
    pv.value('batt_dispatch_auto_can_charge', 1)        # Allow PV charging
    pv.value('batt_dispatch_auto_btm_can_discharge_to_grid', 0)  # No grid export
    pv.value('batt_dispatch_charge_only_system_exceeds_load', 1)  # Smart charging
    pv.value('batt_dispatch_discharge_only_load_exceeds_system', 1)  # Smart discharge
```

## Alternative: Hour-by-Hour Control

For more precise control, convert to direct power arrays:

```python
def apply_hourly_dispatch_schedule(pv: Pvsamv1.Pvsamv1, dispatch_schedule: Dict[str, Any], 
                                  battery_capacity_kwh: float = 13.5) -> None:
    """Apply hourly dispatch schedule using direct power arrays."""
    
    # Set input battery power mode
    pv.value('batt_dispatch_choice', 2)
    
    # Convert percentages to kW values
    grid_charge_kw = []
    discharge_kw = []
    pv_charge_kw = [0.0] * 8760  # PV charging handled automatically
    
    for hour in range(8760):
        # Convert grid charge percentage to kW
        grid_pct = dispatch_schedule['dispatch_manual_percent_gridcharge'][hour]
        grid_charge_kw.append((grid_pct / 100.0) * battery_capacity_kwh)
        
        # Convert discharge percentage to kW  
        discharge_pct = dispatch_schedule['dispatch_manual_percent_discharge'][hour]
        discharge_kw.append((discharge_pct / 100.0) * battery_capacity_kwh)
    
    # Apply to model
    pv.value('dispatch_manual_gridcharge', grid_charge_kw)
    pv.value('dispatch_manual_discharge', discharge_kw)
    pv.value('dispatch_manual_charge', pv_charge_kw)
```

## Data Format Requirements

### Array Lengths
- All arrays must be exactly 8760 hours for annual simulation
- Schedule matrices must be 12×24 (months × hours)
- Period action arrays must be length 6 (for periods 1-6)

### Value Ranges
- **Percentages**: 0-100 (where 100% = full battery capacity)
- **Power values**: 0 to maximum charge/discharge rate (kW)
- **Period numbers**: 1-6 in schedule matrices

### Critical Constraints
- **Period 0 is invalid** - use periods 1-6 only
- **Negative values not allowed** - use 0 for no action
- **Array dimension mismatches will cause SAM execution failure**

## Integration with Current Codebase

To integrate predictive dispatch with the current `pvsamv1_battery.py`:

1. **Add dispatch application after schedule generation** (line 1189)
2. **Choose appropriate method** (period-based recommended for TOU optimization)
3. **Validate schedule before applying** to prevent SAM execution errors
4. **Log dispatch configuration** for debugging and verification

```python
# In main() function after compose_battery_charge_schedule():
dispatch_schedule = compose_battery_charge_schedule(...)

# Apply the schedule to the SAM model
apply_predictive_dispatch_schedule(pv, dispatch_schedule)

# Log configuration for verification
log_section("Applied Dispatch Configuration")
print(f"Dispatch mode: {pv.value('batt_dispatch_choice')}")
print(f"Grid charging enabled: {pv.value('batt_dispatch_auto_can_gridcharge')}")
```

## Validation and Testing

### Essential Checks
1. **Array length validation**: Ensure all arrays are exactly 8760 hours
2. **Value range validation**: Check percentages are 0-100, periods are 1-6
3. **Schedule consistency**: Verify charge/discharge periods don't overlap
4. **Energy balance**: Ensure total energy flows are realistic

### Common Issues
- **Period 0 usage**: Causes SAM execution failure
- **Dimension mismatches**: Arrays must match simulation length exactly  
- **Conflicting settings**: Simultaneous charge/discharge commands
- **Missing control flags**: Can prevent expected behavior

This configuration approach enables precise control over battery operation while respecting SAM's internal constraints and validation requirements.