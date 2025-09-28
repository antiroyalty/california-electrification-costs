# Solar + Storage Functionality Research

## Overview
This document summarizes the findings from reviewing the solar + storage implementation in this California residential electrification cost modeling project. The analysis covers two main files and NREL PySAM module documentation.

## File Analysis

### step9_run_sam_model_for_solar_storage.py

**Primary Purpose**: Orchestrates solar panel sizing and battery storage modeling using NREL's System Advisor Model (SAM) through PySAM Python bindings.

**Key Functionality**:
- **Solar Sizing Algorithm** (lines 18-170): Calculates required solar panel area based on annual load and solar irradiance data
  - Uses NREL weather data with timezone conversion (UTC → Pacific Time, 8-hour shift)
  - Applies Tesla solar panel specifications (420W, 0.193 kW/m²)
  - Accounts for PV cell efficiency (20.6%) and system losses (20%)
  - Formula: `required_area = annual_load_kWh / (irradiance × pv_efficiency × system_performance)`

- **Model Configuration** (lines 172-263): 
  - **PvWatts Model**: Configures solar PV system using JSON presets from `SAM_configuration/`
  - **Battery Model**: Uses Battwatts module with Tesla Powerwall specifications
  - **Dispatch Mode**: Uses self-consumption dispatch (mode 5) for automatic solar utilization optimization
  - **System Integration**: Links solar output to battery charging and load serving

- **Energy Flow Analysis** (lines 265-300):
  - Tracks power flows: `system_to_load`, `batt_to_load`, `grid_to_load`, `system_to_batt`, `grid_to_batt`
  - Validates energy balance: `load = system_to_load + batt_to_load + grid_to_load`
  - Outputs hourly profiles for rate calculations

**Tesla Powerwall Configuration**:
- Battery capacity: 13.5 kWh usable (293.5 Ah @ 50V nominal)
- Charge/discharge rates: Configured via JSON presets
- SOC limits: 30% minimum, 95% maximum, 50% initial (from JSON configuration)
- Usable capacity: 65% of total (between 30-95% SOC)

### pvsamv1_battery.py

**Primary Purpose**: Demonstration script for detailed PV + battery modeling using PySAM.Pvsamv1 and PySAM.Battery modules.

**Key Features**:
- **Advanced PV Modeling**: Uses Pvsamv1 (more detailed than PvWatts) for sophisticated solar modeling
- **Battery Integration**: Full Battery module integration with manual dispatch control
- **Data Visualization**: Comprehensive energy flow analysis and plotting
- **Configuration Management**: JSON-based preset loading from `SAM_Detailed_PV_Battery/`

**Important Implementation Details**:
- **Dispatch Mode**: Uses manual dispatch (mode 3) with predefined schedules from JSON configuration
- **Manual Schedules**: Loads custom dispatch schedules including `dispatch_manual_sched`, `dispatch_manual_percent_discharge`, etc.
- **Power Flow Tracking**: Detailed analysis of energy allocation between load, battery, and grid
- **SOC Management**: Real-time state of charge monitoring and constraints
- **Grid Export Control**: Configurable battery discharge to grid settings

**Visualization Capabilities**:
- First-day hourly power allocation table
- Week-by-week load serving analysis (January vs July)
- SOC tracking and battery utilization patterns

## NREL PySAM Module Documentation

### PySAM.Battery Module

**Core Capabilities**:
- **Battery Chemistry Support**: Lead Acid and Lithium-Ion configurations
- **Multiple Dispatch Strategies**:
  - Peak shaving (reduce demand charges)
  - Grid target power (maintain specific grid draw)
  - Manual dispatch (user-defined schedules)
  - Retail rate dispatch (economic optimization)
  - Self-consumption (maximize solar utilization)
  - Automated economic dispatch

**Key Configuration Parameters**:
- **Capacity Settings**: `batt_Qfull`, `batt_Qnom` (Ah), `batt_Vnom` (V)
- **Power Limits**: `batt_power_charge_max_kwac/kwdc`, `batt_power_discharge_max_kwac/kwdc`
- **Efficiency**: `batt_ac_dc_efficiency`, `batt_dc_ac_efficiency`
- **SOC Constraints**: `batt_minimum_SOC` (30%), `batt_maximum_SOC` (95%), `batt_initial_SOC` (50%)
- **Degradation**: Calendar and cycle life modeling capabilities

**System Integration Features**:
- AC or DC coupling options (`batt_ac_or_dc`)
- Behind-the-meter or front-of-meter configurations
- Grid interconnection limits (`grid_interconnection_limit_kwac`)
- Custom adjustment factors for performance tuning

### PySAM.Pvsamv1 Module

**Advanced Solar Modeling**:
- **Multiple Subarrays**: Up to 4 independent solar arrays with different orientations
- **Tracking Systems**: Fixed, 1-axis, 2-axis, and monthly tilt tracking
- **Detailed Shading**: Beam, diffuse, and timestep-based shading calculations
- **Module Technologies**: Supports various PV technologies and performance models

**System Design Flexibility**:
- **Inverter Options**: Multiple inverter models and configurations
- **Layout Optimization**: String-level modeling and layout optimization
- **Temperature Effects**: Detailed cell temperature and performance modeling
- **Degradation**: Lifetime performance degradation modeling

**Battery Integration**:
- Native integration with Battery module for hybrid systems
- Shared load profiles and dispatch coordination
- Coupled energy flow optimization

## Implementation Recommendations

### Current Strengths
1. **Robust Solar Sizing**: Physics-based approach using actual NREL irradiance data
2. **Tesla Integration**: Realistic Powerwall specifications and performance modeling
3. **Energy Balance Validation**: Comprehensive flow tracking and validation
4. **Timezone Handling**: Proper alignment of weather and load data to Pacific Time

### Areas for Enhancement

#### 1. Battery Dispatch Optimization
- **step9**: Uses self-consumption dispatch (mode 5) for automatic solar utilization
- **pvsamv1_battery**: Uses manual dispatch (mode 3) with predefined schedules
- **Recommendation**: Implement retail rate dispatch (mode 4) for TOU optimization
- **Implementation**: Configure utility rate structures in `UtilityRateStructure` group

#### 2. Grid Export Controls
```python
# Configure grid export settings
battery.BatteryDispatch.batt_dispatch_auto_btm_can_discharge_to_grid = 0  # Disable export
battery.BatteryDispatch.grid_interconnection_limit_kwac = inverter_capacity
```

#### 3. Advanced Dispatch Scheduling
- **Manual Dispatch**: Use `dispatch_manual_sched` for custom TOU strategies
- **Forecasting**: Implement `batt_load_ac_forecast` and `batt_pv_ac_forecast` for predictive dispatch

#### 4. Battery Sizing Optimization
- **Current**: Fixed Tesla Powerwall configuration
- **Enhancement**: Dynamic sizing based on load patterns and rate structures
- **Approach**: Iterate battery capacity to optimize economic performance

#### 5. Degradation Modeling
```python
# Enable detailed battery degradation
battery.BatteryCell.batt_life_model = 1  # Enable cycle and calendar aging
battery.BatteryCell.batt_calendar_choice = 1  # Enable calendar degradation
```

### Integration Patterns

#### PvWatts vs Pvsamv1 Selection
- **PvWatts** (step9): Simpler, faster, suitable for high-level analysis with self-consumption dispatch
- **Pvsamv1** (pvsamv1_battery): More detailed modeling with manual dispatch control for complex scenarios

#### Configuration Management
- **JSON Presets**: Maintain separate presets for different scenarios
- **Parameter Validation**: Implement validation for critical parameters
- **Version Control**: Track SAM configuration changes for reproducibility

#### Data Flow Architecture
```
Weather Data (NREL) → Solar Sizing → PV/Battery Modeling → Energy Flows → Rate Calculations
```

## Battery State of Charge (SOC) Configuration

Both implementations use consistent SOC constraints based on Tesla Powerwall operational parameters:

**Current SOC Settings**:
- **Minimum SOC**: 30% (deep discharge protection)
- **Maximum SOC**: 95% (overcharge protection and battery longevity)
- **Initial SOC**: 50% (simulation starting point)
- **Usable Range**: 65% of total capacity (30-95% SOC)

**Rationale**:
- **30% Minimum**: Protects lithium-ion cells from deep discharge damage and maintains reserve capacity for emergency backup
- **95% Maximum**: Prevents overcharging and reduces calendar aging, extending battery life
- **65% Usable**: Reflects real-world Tesla Powerwall operation balancing performance with longevity

**Impact on Analysis**:
- Effective storage capacity: 13.5 kWh × 0.65 = 8.8 kWh available for daily cycling
- Battery never fully discharges, ensuring backup power availability
- Conservative operation extends system lifetime and maintains warranty compliance

## Critical Implementation Notes

### Timezone Synchronization
Both files implement 8-hour UTC to Pacific Time conversion for weather data alignment with load profiles. This is crucial for accurate energy balance calculations.

### Energy Units Consistency
- **Load Profiles**: kW (instantaneous power)
- **Energy Production**: kWh (energy over time)
- **Battery Capacity**: kWh (energy storage)
- **Solar Capacity**: kW (peak DC power)

### Validation Requirements
1. **Energy Balance**: `load = system_to_load + batt_to_load + grid_to_load` must balance
2. **SOC Constraints**: Battery SOC must remain within defined limits
3. **Power Limits**: Charge/discharge must respect battery power ratings
4. **Grid Limits**: Export must respect interconnection agreements

### Performance Considerations
- **Model Complexity**: Pvsamv1 provides more accuracy but longer execution times
- **Iteration Strategy**: Consider multi-year simulations for degradation analysis
- **Memory Usage**: 8760-hour arrays for multiple variables require careful memory management

## Dispatch Mode Comparison

### step9_run_sam_model_for_solar_storage.py
- **Mode**: Self-consumption dispatch (mode 5)
- **Behavior**: Automatically maximizes solar utilization without custom scheduling
- **Configuration**: Minimal dispatch configuration required
- **SOC Constraints**: Uses default/configured values (likely 30% min, 95% max)
- **Use Case**: High-level analysis for cost modeling across many counties

### pvsamv1_battery.py  
- **Mode**: Manual dispatch (mode 3)
- **Behavior**: Uses predefined schedules from JSON configuration files
- **Configuration**: Detailed manual schedules including `dispatch_manual_sched`, `dispatch_manual_percent_discharge`
- **SOC Constraints**: 30% minimum, 95% maximum, 50% initial (from JSON presets)
- **Effective Range**: 65% of total battery capacity is usable for cycling
- **Use Case**: Sophisticated time-of-use strategies and detailed analysis

This research provides the foundation for implementing robust solar + storage functionality that accurately models residential electrification scenarios across California's diverse climate and utility rate environments.