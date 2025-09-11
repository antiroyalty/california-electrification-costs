#!/usr/bin/env python3
"""
Test script to verify the appliance breakdown fixes in step16_display_key_metrics_maps.py
"""

import sys
import os
import pandas as pd

# Add current directory to Python path
sys.path.append('.')

def test_appliance_breakdown_fix():
    """Test the fixed appliance breakdown data loading function."""
    
    # Import the fixed function
    from step16_display_key_metrics_maps import load_appliance_breakdown_data
    
    # Test configuration
    base_input_dir = "data/loadprofiles"
    scenario = "baseline"
    housing_type = "single-family-detached"
    county_slug = "alameda"
    
    print("Testing fixed appliance breakdown data loading...")
    print(f"Configuration: {scenario}/{housing_type}/{county_slug}")
    
    # Load data using the fixed function
    appliance_data = load_appliance_breakdown_data(
        base_input_dir, scenario, housing_type, county_slug
    )
    
    print(f"\nResults:")
    print(f"Number of categories: {len(appliance_data)}")
    
    if appliance_data and "Data Not Available" not in appliance_data:
        print("✅ SUCCESS: Real appliance data loaded!")
        
        # Sort by consumption for better display
        sorted_data = dict(sorted(appliance_data.items(), key=lambda x: x[1], reverse=True))
        
        total_consumption = sum(appliance_data.values())
        print(f"\nTotal annual consumption: {total_consumption:,.0f} kWh")
        
        print(f"\nBreakdown by category:")
        for category, consumption in sorted_data.items():
            percentage = (consumption / total_consumption) * 100
            print(f"  {category}: {consumption:,.0f} kWh ({percentage:.1f}%)")
            
        # Verify reasonable consumption ranges
        if 15000 <= total_consumption <= 30000:
            print(f"\n✅ Total consumption ({total_consumption:,.0f} kWh) is in expected range")
        else:
            print(f"\n⚠️  WARNING: Total consumption ({total_consumption:,.0f} kWh) may be outside expected range (15k-30k kWh)")
            
    else:
        print("❌ FAILED: No real appliance data loaded")
        print(f"Returned data: {appliance_data}")

if __name__ == "__main__":
    test_appliance_breakdown_fix()