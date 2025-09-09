#!/usr/bin/env python3

# Simple test to verify appliance data
import pandas as pd
import os

# Test electricity data directly
electricity_file = "data/loadprofiles/baseline/single-family-detached/alameda/electricity_loads_alameda.csv"

if os.path.exists(electricity_file):
    print(f"Loading {electricity_file}")
    df = pd.read_csv(electricity_file)
    print(f"Shape: {df.shape}")
    print(f"Columns: {list(df.columns)}")
    
    # Test specific columns
    test_columns = [
        'out.electricity.ceiling_fan.energy_consumption',
        'out.electricity.plug_loads.energy_consumption',
        'out.electricity.refrigerator.energy_consumption'
    ]
    
    for col in test_columns:
        if col in df.columns:
            total = df[col].sum()
            print(f"{col}: {total:.2f} kWh annually")
        else:
            print(f"Column not found: {col}")
            
    # Test gas data
    gas_file = "data/loadprofiles/baseline/single-family-detached/alameda/gas_loads_alameda.csv"
    if os.path.exists(gas_file):
        print(f"\nLoading {gas_file}")
        df_gas = pd.read_csv(gas_file)
        print(f"Gas shape: {df_gas.shape}")
        print(f"Gas columns: {list(df_gas.columns[:10])}")
        
        # Test specific gas columns
        gas_test_columns = [
            'out.natural_gas.heating.energy_consumption.gas.building_avg.kwh',
            'out.natural_gas.hot_water.energy_consumption.gas.building_avg.kwh',
            'out.natural_gas.range_oven.energy_consumption.gas.building_avg.kwh'
        ]
        
        for col in gas_test_columns:
            if col in df_gas.columns:
                total = df_gas[col].sum()
                print(f"{col}: {total:.2f} kWh annually")
            else:
                print(f"Gas column not found: {col}")
                
else:
    print(f"File not found: {electricity_file}")