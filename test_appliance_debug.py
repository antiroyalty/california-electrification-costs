#!/usr/bin/env python3

# Quick debug script for appliance breakdown data loading
import sys
import os
sys.path.append('.')

import step16_display_key_metrics_maps as s16

# Test with baseline scenario for alameda
print("Testing appliance breakdown loading...")
print("=" * 50)

data = s16.load_appliance_breakdown_data(
    base_input_dir='data/loadprofiles', 
    scenario='baseline', 
    housing_type='single-family-detached', 
    county_slug='alameda'
)

print("=" * 50)
print(f"Final result: {data}")

if data:
    print("SUCCESS: Found appliance data!")
    for category, value in data.items():
        print(f"  {category}: {value:,.0f} kWh")
else:
    print("PROBLEM: No appliance data found")