"""
County-specific gasoline cost and vehicle miles traveled helper for ICE vehicle calculations.

This module provides county-specific data for gasoline prices and vehicle miles traveled
to enable accurate cost calculations for ICE vehicles in different California counties.
"""

from typing import Dict, Optional
from main_helpers import slugify_county_name

# County-specific gasoline costs in dollars per gallon
# Data should be updated regularly to reflect current market conditions
COUNTY_GASOLINE_COSTS = {
    # Northern California Counties
    "alameda": 4.581,
    "contra-costa": 4.589,
    "marin": 4.721,
    "napa": 4.836,
    "san-francisco": 4.663,
    "san-mateo": 4.735,
    "santa-clara": 4.525,
    "santa-cruz": 4.622,
    "solano": 4.561,
    "sonoma": 4.783,
    "lake": 4.515,
    "mendocino": 4.809,
    "humboldt": 5.069,
    "del-norte": 4.834,
    "siskiyou": 4.712,
    "modoc": 4.673,
    "trinity": 5.150,
    "shasta": 4.377,
    "lassen": 4.773,
    "plumas": 4.771,
    "sierra": 5.173,
    "nevada": 5.067,
    "placer": 4.613,
    "el-dorado": 4.642,
    "alpine": 0,
    "amador": 4.615,
    "calaveras": 4.529,
    "tuolumne": 4.608,
    "mariposa": 4.665,
    "mono": 5.822,
    
    # Central California Counties
    "monterey": 4.765,
    "san-benito": 4.668,
    "san-luis-obispo": 4.855,
    "santa-barbara": 4.466,
    "ventura": 4.524,
    "kern": 4.461,
    "kings": 4.383,
    "tulare": 4.487,
    "fresno": 4.575,
    "madera": 4.554,
    "merced": 4.451,
    "stanislaus": 4.299,
    "san-joaquin": 4.416,
    "sacramento": 4.458,
    "yolo": 4.488,
    "colusa": 4.674,
    "glenn": 4.644,
    "butte": 4.476,
    "tehama": 4.402,
    "sutter": 4.309,
    "yuba": 4.314,
    "inyo": 4.755,
    
    # Southern California Counties
    "los-angeles": 4.468,
    "orange": 4.415,
    "riverside": 4.315,
    "san-bernardino": 4.354,
    "san-diego": 4.563,
    "imperial": 4.259
}

# County-specific annual vehicle miles traveled (VMT)
# Based on regional driving patterns and urban/rural characteristics
COUNTY_ANNUAL_VMT = {
    # Northern California Counties
    "alameda": 0,
    "contra-costa": 0,
    "marin": 0,
    "napa": 0,
    "san-francisco": 0,
    "san-mateo": 0,
    "santa-clara": 0,
    "santa-cruz": 0,
    "solano": 0,
    "sonoma": 0,
    "lake": 0,
    "mendocino": 0,
    "humboldt": 0,
    "del-norte": 0,
    "siskiyou": 0,
    "modoc": 0,
    "shasta": 0,
    "lassen": 0,
    "plumas": 0,
    "sierra": 0,
    "nevada": 0,
    "placer": 0,
    "el-dorado": 0,
    "alpine": 0,
    "amador": 0,
    "calaveras": 0,
    "tuolumne": 0,
    "mariposa": 0,
    "mono": 0,
    
    # Central California Counties
    "monterey": 0,
    "san-benito": 0,
    "san-luis-obispo": 0,
    "santa-barbara": 0,
    "ventura": 0,
    "kern": 0,
    "kings": 0,
    "tulare": 0,
    "fresno": 0,
    "madera": 0,
    "merced": 0,
    "stanislaus": 0,
    "san-joaquin": 0,
    "sacramento": 0,
    "yolo": 0,
    "colusa": 0,
    "glenn": 0,
    "butte": 0,
    "tehama": 0,
    "sutter": 0,
    "yuba": 0,
    "inyo": 0,
    
    # Southern California Counties
    "los-angeles": 0,
    "orange": 0,
    "riverside": 0,
    "san-bernardino": 0,
    "san-diego": 0,
    "imperial": 0
}

# Default values for counties not in the database
DEFAULT_GASOLINE_COST = 0.0  # dollars per gallon
DEFAULT_ANNUAL_VMT = 0        # miles per year

def get_gasoline_cost_for_county(county_name: str) -> float:
    county_slug = slugify_county_name(county_name)
    return COUNTY_GASOLINE_COSTS.get(county_slug, DEFAULT_GASOLINE_COST)


def get_annual_vmt_for_county(county_name: str) -> int:
    county_slug = slugify_county_name(county_name)
    return COUNTY_ANNUAL_VMT.get(county_slug, DEFAULT_ANNUAL_VMT)


def calculate_annual_fuel_cost(county_name: str, 
                             fuel_efficiency_mpg: float,
                             custom_annual_miles: Optional[int] = None) -> Dict[str, float]:
    county_slug = slugify_county_name(county_name)
    gas_price = get_gasoline_cost_for_county(county_name)
    annual_miles = custom_annual_miles if custom_annual_miles else get_annual_vmt_for_county(county_name)
    
    annual_gallons = annual_miles / fuel_efficiency_mpg
    annual_fuel_cost = annual_gallons * gas_price
    
    return {
        "county": county_name,
        "county_slug": county_slug,
        "gas_price_per_gallon": gas_price,
        "annual_miles": annual_miles,
        "fuel_efficiency_mpg": fuel_efficiency_mpg,
        "annual_gallons": annual_gallons,
        "annual_fuel_cost": annual_fuel_cost,
        "fuel_cost_per_mile": annual_fuel_cost / annual_miles
    }


def get_county_driving_profile(county_name: str) -> Dict[str, any]:
    """
    Get comprehensive driving profile for a county including costs and VMT.
    
    Args:
        county_name: County name
        
    Returns:
        Dictionary with complete county driving profile
    """
    county_slug = slugify_county_name(county_name)
    
    # Categorize counties by region for additional context
    norcal_counties = [
        "alameda", "contra-costa", "marin", "napa", "san-francisco", 
        "san-mateo", "santa-clara", "santa-cruz", "solano", "sonoma"
    ]
    
    socal_counties = [
        "los-angeles", "orange", "riverside", "san-bernardino", "san-diego", "imperial"
    ]
    
    if county_slug in norcal_counties:
        region = "Northern California"
    elif county_slug in socal_counties:
        region = "Southern California"
    else:
        region = "Central California"
    
    return {
        "county": county_name,
        "county_slug": county_slug,
        "region": region,
        "gas_price_per_gallon": get_gasoline_cost_for_county(county_name),
        "annual_vmt": get_annual_vmt_for_county(county_name),
        "has_custom_data": county_slug in COUNTY_GASOLINE_COSTS and county_slug in COUNTY_ANNUAL_VMT
    }


def compare_counties_fuel_costs(county_names: list, fuel_efficiency_mpg: float = 28.0) -> Dict[str, Dict]:
    """
    Compare fuel costs across multiple counties.
    
    Args:
        county_names: List of county names to compare
        fuel_efficiency_mpg: Vehicle fuel efficiency for comparison
        
    Returns:
        Dictionary with fuel cost comparisons for each county
    """
    comparison = {}
    
    for county in county_names:
        comparison[county] = calculate_annual_fuel_cost(county, fuel_efficiency_mpg)
    
    # Add ranking information
    sorted_by_cost = sorted(comparison.items(), key=lambda x: x[1]['annual_fuel_cost'])
    
    for i, (county, data) in enumerate(sorted_by_cost):
        comparison[county]['cost_rank'] = i + 1
        comparison[county]['cost_rank_total'] = len(county_names)
    
    return comparison


# Example usage and test data
if __name__ == "__main__":
    # Test the helper functions
    test_counties = ["San Francisco County", "Los Angeles County", "Riverside County", "Alameda County"]
    
    print("County-Specific Gasoline Cost Analysis")
    print("=" * 50)
    
    for county in test_counties:
        profile = get_county_driving_profile(county)
        fuel_calc = calculate_annual_fuel_cost(county, 28.0)
        
        print(f"\n{county}:")
        print(f"  Region: {profile['region']}")
        print(f"  Gas Price: ${profile['gas_price_per_gallon']:.2f}/gallon")
        print(f"  Annual VMT: {profile['annual_vmt']:,} miles")
        print(f"  Annual Fuel Cost (28 MPG): ${fuel_calc['annual_fuel_cost']:,.2f}")
        print(f"  Cost per Mile: ${fuel_calc['fuel_cost_per_mile']:.3f}")
    
    print(f"\n{'='*50}")
    print("County Comparison (28 MPG vehicle)")
    print(f"{'='*50}")
    
    comparison = compare_counties_fuel_costs(test_counties, 28.0)
    for county, data in sorted(comparison.items(), key=lambda x: x[1]['cost_rank']):
        print(f"#{data['cost_rank']}: {county} - ${data['annual_fuel_cost']:,.2f}/year")