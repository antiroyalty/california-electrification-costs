"""
Step 16: Display Key Metrics Maps

Display diagnostic maps for key metrics in a single HTML file:
- Average solar panel size in county
- Total annual electricity bill in county, in $
- Total annual gas bill in county, in $
- Total annual energy consumption (electricity kWh, gas therms)
- Solar+storage annual savings vs non-solar deployment, in $
- Capital costs (net outlay with full incentives) for scenario appliances, in $
- Payback period (years) for electrification investments with full incentives
- Net grid consumption (kWh) - what the meter sees after solar+storage
- Total energy consumption (kWh) - gross load before solar offset
"""

import os
import pandas as pd
import folium
from helpers.maps_helpers import (
    initialize_map, load_cost_data, add_choropleth_layer, 
    add_centroid_labels,
    get_latest_csv_file
)
from helpers.main_helpers import log, slugify_county_name, to_decimal_number, get_scenario_path, norcal_counties, central_counties, socal_counties, git_short_sha
from helpers.utility_helpers import get_utility_for_county

# Chart builders live in helpers to keep the pipeline strictly linear
from helpers.diagnostics_helpers import (
    load_appliance_breakdown_data,
    create_appliance_breakdown_chart,
)


# Shared run identifiers for repeatable, versioned outputs
# No timestamp in filenames; use only git short SHA for versioning

GIT_SHORT_SHA = git_short_sha()


def format_currency_with_sign(value: float) -> str:
    """Format currency values with appropriate sign for savings/costs."""
    if value > 0:
        return f"+${to_decimal_number(abs(value))}"
    elif value < 0:
        return f"-${to_decimal_number(abs(value))}"
    else:
        return "$0"


def format_payback_period(years: float) -> str:
    """Format payback period with appropriate handling for edge cases."""
    if years >= 100:
        return ">100 years"
    elif years <= -100 or years < 0:
        return "No payback (costs more)"
    else:
        return f"{years:.1f} years"


# Bin ranges for map visualizations
SOLAR_SIZE_BINS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
ENERGY_CONSUMPTION_BINS = [0, 2500, 5000, 7500, 10000, 12500, 15000, 17500, 200000]
ELECTRICITY_BILL_BINS = [0, 1000, 2000, 3000, 4000, 5000, 6000, 8000, 10000]
GAS_BILL_BINS = [0, 500, 1000, 1500, 2000, 2500, 3000, 4000]
SAVINGS_BINS = [-2000, -1000, -500, 0, 500, 1000, 1500, 2000, 3000]
CAPITAL_COSTS_BINS = [-1000, 0, 5000, 10000, 15000, 20000, 25000, 30000, 40000, 50000, 100000]
PAYBACK_PERIOD_BINS = [0, 5, 10, 15, 20, 25, 30, 50, 100, 120]
NET_GRID_CONSUMPTION_BINS = [0, 2500, 5000, 7500, 10000, 12500, 15000,]
TOTAL_ELECTRICITY_CONSUMPTION_BINS = [0, 2000, 4000, 6000, 8000, 10000, 12000, 14000, 16000]
BATTERY_ENERGY_BINS = [0, 500, 1000, 1500, 2000, 2500, 3000]
SOLAR_ENERGY_BINS = [0, 2500, 5000, 7500]


def load_solar_data(base_input_dir: str, scenario: str, housing_type: str, county_slug: str) -> float:
    """
    Load solar capacity data from electrified assets CSV using capital_costs_helper.
    """
    try:
        from helpers.capital_costs_helper import load_electrified_assets
        from helpers.main_helpers import get_scenario_path, slugify_county_name
        
        # Get the scenario path and load electrified assets
        scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
        assets_mapping = load_electrified_assets(scenario_path)
        
        if county_slug in assets_mapping:
            return float(assets_mapping[county_slug])
        else:
            return 0.0
            
    except Exception as e:
        print(f"Warning: Could not load solar data for {county_name}: {e}")
        return 0.0


def load_energy_consumption_data(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str
) -> tuple[float, float]:
    """
    Load annual energy consumption data for county.
    Returns (electricity_kwh, gas_therms)
    """
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    file_name = f"loadprofiles_for_rates_{county_slug}.csv"
    file_path = os.path.join(county_dir, file_name)

    if not os.path.isfile(file_path):
        print(f"Warning: Cannot find {file_path}")
        return 0.0, 0.0

    try:
        df = pd.read_csv(file_path, low_memory=False)
        electricity_kwh = float(df["default.electricity.kwh"].sum())
        gas_therms = float(df["default.gas.therms"].sum())
        return electricity_kwh, gas_therms
    except Exception as exc:
        print(f"Warning: could not parse {file_path}: {exc}")
        return 0.0, 0.0


def load_solar_savings_data(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
    rate_plan: str = "PG&E.E-TOU-D+PG&E.G-1"
) -> float:
    """
    Load annual cost difference between solar+storage and non-solar scenarios.
    Returns savings (positive) or extra costs (negative) in dollars.
    """
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    
    # Find the latest total annual costs file
    results_dir = os.path.join(county_dir, "results", "totals")
    if not os.path.exists(results_dir):
        print(f"Warning: Results directory not found: {results_dir}")
        return 0.0
    
    file_path = get_latest_csv_file(results_dir, f"RESULTS_total_annual_costs_{county_slug}")
    if not file_path:
        print(f"Warning: No total costs file found for {county_slug}")
        return 0.0
    
    try:
        df = pd.read_csv(file_path, low_memory=False)
        
        # Find baseline and solar+storage costs
        baseline_cost = None
        solar_cost = None
        
        column_name = f"total.{rate_plan}"
        if column_name not in df.columns:
            # Use first available column
            column_name = [col for col in df.columns if col.startswith("total.")][0]
        
        for _, row in df.iterrows():
            scenario_name = row['scenario']
            if scenario_name == scenario:
                baseline_cost = float(row[column_name])
            elif scenario_name == f"{scenario}.solarstorage":
                solar_cost = float(row[column_name])
        
        if baseline_cost is not None and solar_cost is not None:
            # Return savings (positive = savings, negative = extra cost)
            return baseline_cost - solar_cost
        else:
            print(f"Warning: Could not find both baseline and solar costs for {county_slug}")
            return 0.0
            
    except Exception as exc:
        print(f"Warning: could not parse {file_path}: {exc}")
        return 0.0


def load_capital_costs_data(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str
) -> float:
    """
    Load capital costs for the scenario from step15 capital costs files.
    Returns the net outlay with PV/Storage under full incentives (to match payback numerator).
    """
    # Capital costs files are in base_input_dir/capital_costs/
    capital_costs_dir = os.path.join(base_input_dir, "capital_costs")
    if not os.path.exists(capital_costs_dir):
        print(f"Warning: Capital costs directory not found: {capital_costs_dir}")
        return 0.0
    
    base_name = f"{scenario}_{housing_type.replace('-', '_')}"
    summary_with_pv = os.path.join(capital_costs_dir, f"capital_costs_summary_with_pv_{base_name}.csv")

    # Preferred source: summary with PV, using net_outlay_full_with_pv
    if os.path.exists(summary_with_pv):
        try:
            df = pd.read_csv(summary_with_pv, low_memory=False)
            row = df[df['county_slug'] == county_slug]
            if row.empty:
                print(f"Warning: No capital summary with PV for {county_slug}")
                return 0.0
            if 'net_outlay_full_with_pv' in row.columns:
                return float(row.iloc[0]['net_outlay_full_with_pv'])
            elif 'net_outlay_full' in row.columns:
                return float(row.iloc[0]['net_outlay_full'])
            else:
                print(f"Warning: net_outlay columns missing in {summary_with_pv}")
                return 0.0
        except Exception as exc:
            print(f"Warning: could not parse {summary_with_pv}: {exc}")
            return 0.0

    # Fallback: legacy detailed ledger sum
    file_path = os.path.join(capital_costs_dir, f"capital_costs_{base_name}.csv")
    if not os.path.exists(file_path):
        print(f"Warning: Capital costs file not found: {file_path}")
        return 0.0
    try:
        df = pd.read_csv(file_path, low_memory=False)
        county_name = county_slug.replace("-", " ").title()
        if not county_name.endswith(" County"):
            county_name += " County"
        county_data = df[(df['county'].str.contains(county_name.replace(" County", ""), case=False, na=False)) &
                         (df['incentive_scenario'] == 'full_incentives')]
        if county_data.empty:
            print(f"Warning: No capital costs data found for {county_name} with full incentives")
            return 0.0
        return float(county_data['net_cost'].sum())
    except Exception as exc:
        print(f"Warning: could not parse capital costs file {file_path}: {exc}")
        return 0.0


def load_payback_period_data(
    scenario: str,
    housing_type: str,
    county_slug: str
) -> float:
    """
    Load payback period data from step16_payback_periods.py output.
    Returns payback period in years with full incentives.
    """
    # Payback period files are in data/results/{housing_type}/
    payback_file = os.path.join("data", "results", housing_type, f"payback_periods_{scenario}.csv")
    
    if not os.path.exists(payback_file):
        print(f"Warning: Payback periods file not found: {payback_file}")
        return 0.0
    
    try:
        df = pd.read_csv(payback_file, low_memory=False)
        
        # Convert county_slug back to county name for matching
        county_name = county_slug.replace("-", " ").title()
        if not county_name.endswith(" County"):
            county_name += " County"
        
        # Filter for this county and full incentives scenario
        county_data = df[
            (df['county'].str.contains(county_name.replace(" County", ""), case=False, na=False)) &
            (df['incentive_scenario'] == 'full_incentives')
        ]
        
        if county_data.empty:
            print(f"Warning: No payback period data found for {county_name} with full incentives")
            return 0.0
        
        # Check if payback_period_years column exists
        if 'payback_period_years' not in df.columns:
            print(f"Warning: payback_period_years column not found in {payback_file}")
            return 0.0
        
        # Get payback period (should be only one row per county-incentive combination)
        payback_years = county_data['payback_period_years'].iloc[0]
        
        # Handle infinite payback periods
        if payback_years == float('inf') or payback_years > 100:
            return 100.0  # Cap at 100 years for display purposes
        
        return float(payback_years)
        
    except Exception as exc:
        print(f"Warning: could not parse payback periods file {payback_file}: {exc}")
        return 0.0


def load_capital_component(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
    component: str
) -> float:
    """
    Load a single PV/Storage component value from capital_costs_summary_with_pv file.
    Component should be one of: pv_capex, storage_capex, pv_incentives_full,
    storage_incentives_full, pv_storage_net_full.
    """
    capital_costs_dir = os.path.join(base_input_dir, "capital_costs")
    base_name = f"{scenario}_{housing_type.replace('-', '_')}"
    summary_with_pv = os.path.join(capital_costs_dir, f"capital_costs_summary_with_pv_{base_name}.csv")
    if not os.path.exists(summary_with_pv):
        print(f"Warning: capital costs summary with PV not found: {summary_with_pv}")
        return 0.0
    try:
        df = pd.read_csv(summary_with_pv, low_memory=False)
        row = df[df['county_slug'] == county_slug]
        if row.empty or component not in row.columns:
            print(f"Warning: {component} not available for {county_slug}")
            return 0.0
        return float(row.iloc[0][component])
    except Exception as exc:
        print(f"Warning: could not parse {summary_with_pv}: {exc}")
        return 0.0


def load_effective_electricity_price(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str
) -> float:
    """
    Effective price ($/kWh) ≈ min annual_electricity_cost among utility tariffs / annual_kWh (default scenario).
    Uses results/electricity CSV for costs and loadprofiles_for_rates for kWh.
    """
    try:
        # Annual kWh from loadprofiles_for_rates
        county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
        lfr_path = os.path.join(county_dir, f"loadprofiles_for_rates_{county_slug}.csv")
        if not os.path.exists(lfr_path):
            return 0.0
        df_lfr = pd.read_csv(lfr_path, low_memory=False)
        if 'default.electricity.kwh' not in df_lfr.columns:
            return 0.0
        annual_kwh = float(df_lfr['default.electricity.kwh'].sum())
        if annual_kwh <= 0:
            return 0.0

        # Annual electricity cost from results/electricity for this county & scenario
        scen_path = get_scenario_path(base_input_dir, scenario, housing_type)
        elec_dir = os.path.join(scen_path, county_slug, 'results', 'electricity')
        res_path = get_latest_csv_file(elec_dir, f"RESULTS_electricity_annual_costs_{county_slug}")
        df = pd.read_csv(res_path, index_col='scenario')
        # Select the scenario row (not .solarstorage)
        if scenario in df.index:
            row = df.loc[scenario]
        else:
            # Fallback to first row
            row = df.iloc[0]
        util = get_utility_for_county(county_slug)
        # Filter columns for this utility
        cols = [c for c in row.index if c.startswith(f"electricity.{util}.")]
        if not cols:
            cols = [c for c in row.index if c.startswith("electricity.")]
        if not cols:
            return 0.0
        # Choose minimum annual cost among available tariffs for this utility
        annual_cost = float(min(row[c] for c in cols if pd.notnull(row[c])))
        return annual_cost / annual_kwh if annual_kwh > 0 else 0.0
    except Exception as exc:
        print(f"Warning: could not compute effective price for {county_slug}: {exc}")
        return 0.0


def load_total_solar_generation_kwh(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str
) -> float:
    """
    Total PV generation ≈ (System to Load) + (System to Battery) [+ (System to Grid) if present].
    """
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    candidates = [
        os.path.join(county_dir, f"solar_storage_dispatch_profiles_{county_slug}.csv"),
        os.path.join(county_dir, f"solar_storage_dispatch_profiles_{scenario}_{county_slug}.csv"),
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                df = pd.read_csv(path)
                val = 0.0
                if 'System to Load' in df.columns:
                    val += float(df['System to Load'].sum())
                if 'System to Battery' in df.columns:
                    val += float(df['System to Battery'].sum())
                if 'System to Grid' in df.columns:
                    val += float(df['System to Grid'].sum())
                return val
            except Exception as exc:
                print(f"Warning: could not parse PV generation from {path}: {exc}")
    return 0.0


def load_pv_capacity_factor(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str
) -> float:
    """
    Capacity factor = total PV generation (kWh) / (solar_kw × 8760).
    """
    gen = load_total_solar_generation_kwh(base_input_dir, scenario, housing_type, county_slug)
    # Get solar size
    capital_costs_dir = os.path.join(base_input_dir, "capital_costs")
    base_name = f"{scenario}_{housing_type.replace('-', '_')}"
    summary_with_pv = os.path.join(capital_costs_dir, f"capital_costs_summary_with_pv_{base_name}.csv")
    if not os.path.exists(summary_with_pv) or gen <= 0:
        return 0.0
    try:
        df = pd.read_csv(summary_with_pv, low_memory=False)
        row = df[df['county_slug'] == county_slug]
        if row.empty or 'solar_kw' not in row.columns:
            return 0.0
        kw = float(row.iloc[0]['solar_kw'])
        if kw <= 0:
            return 0.0
        return gen / (kw * 8760.0)
    except Exception as exc:
        print(f"Warning: could not compute capacity factor for {county_slug}: {exc}")
        return 0.0


def load_self_supply_ratio(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str
) -> float:
    """
    Self-supply ratio = 1 − (Grid to Load kWh / Load Profile kWh)
    """
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    for pattern in [
        f"solar_storage_dispatch_profiles_{county_slug}.csv",
        f"solar_storage_dispatch_profiles_{scenario}_{county_slug}.csv"
    ]:
        path = os.path.join(county_dir, pattern)
        if os.path.exists(path):
            try:
                df = pd.read_csv(path)
                if 'Grid to Load' in df.columns and 'Load Profile' in df.columns:
                    grid = float(df['Grid to Load'].sum())
                    load = float(df['Load Profile'].sum())
                    return 1.0 - (grid / load) if load > 0 else 0.0
            except Exception as exc:
                print(f"Warning: could not compute self-supply for {county_slug}: {exc}")
    return 0.0


def load_peak_period_load_share(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str
) -> float:
    """
    Peak-period load share = sum(load 16–21) / sum(load) using 'Load Profile' from SAM CSV.
    """
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    path = os.path.join(county_dir, f"solar_storage_dispatch_profiles_{county_slug}.csv")
    if not os.path.exists(path):
        # Try alternate naming
        path = os.path.join(county_dir, f"solar_storage_dispatch_profiles_{scenario}_{county_slug}.csv")
        if not os.path.exists(path):
            return 0.0
    try:
        df = pd.read_csv(path, parse_dates=[0], index_col=0)
        if 'Load Profile' not in df.columns:
            return 0.0
        # Filter hours 16–20 inclusive (i.e., 4–9pm = 16–21 exclusive upper bound)
        hours = df.index.hour
        peak_mask = (hours >= 16) & (hours < 21)
        peak_sum = float(df.loc[peak_mask, 'Load Profile'].sum())
        total_sum = float(df['Load Profile'].sum())
        return (peak_sum / total_sum) if total_sum > 0 else 0.0
    except Exception as exc:
        print(f"Warning: could not compute peak load share for {county_slug}: {exc}")
        return 0.0


def load_net_grid_consumption_data(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str
) -> float:
    """
    Load net grid consumption (what the meter sees after solar+storage).
    Returns annual kWh consumed from the grid.
    """
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    
    # Try to find SAM optimized load profiles file
    sam_file_patterns = [
        f"solar_storage_dispatch_profiles_{county_slug}.csv",
        f"solar_storage_dispatch_profiles_{scenario}_{county_slug}.csv"
    ]
    
    for pattern in sam_file_patterns:
        sam_file_path = os.path.join(county_dir, pattern)
        if os.path.exists(sam_file_path):
            try:
                df = pd.read_csv(sam_file_path)
                if 'Grid to Load' in df.columns:
                    # Sum hourly values to get annual kWh
                    annual_net_grid = df['Grid to Load'].sum()
                    return float(annual_net_grid)
            except Exception as e:
                print(f"Warning: Error reading {sam_file_path}: {e}")
                continue
    
    # Fallback: try loadprofiles_for_rates file
    rates_file = os.path.join(county_dir, f"loadprofiles_for_rates_{county_slug}.csv")
    if os.path.exists(rates_file):
        try:
            df = pd.read_csv(rates_file)
            if 'solarstorage.electricity.kwh' in df.columns:
                annual_net_grid = df['solarstorage.electricity.kwh'].sum()
                return float(annual_net_grid)
        except Exception as e:
            print(f"Warning: Error reading {rates_file}: {e}")
    
    print(f"Warning: Could not find net grid consumption data for {county_slug} in scenario {scenario}")
    return 0.0


def load_total_consumption_data(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str
) -> float:
    """
    Load total energy consumption (gross load before solar offset).
    Returns annual kWh of total consumption.
    """
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    
    # Try to find SAM optimized load profiles file
    sam_file_patterns = [
        f"solar_storage_dispatch_profiles_{county_slug}.csv",
        f"solar_storage_dispatch_profiles_{scenario}_{county_slug}.csv"
    ]
    
    for pattern in sam_file_patterns:
        sam_file_path = os.path.join(county_dir, pattern)
        if os.path.exists(sam_file_path):
            try:
                df = pd.read_csv(sam_file_path)
                if 'Load Profile' in df.columns:
                    # Sum hourly values to get annual kWh
                    annual_total = df['Load Profile'].sum()
                    return float(annual_total)
            except Exception as e:
                print(f"Warning: Error reading {sam_file_path}: {e}")
                continue
    
    # Fallback: try loadprofiles_for_rates file (baseline consumption)
    rates_file = os.path.join(county_dir, f"loadprofiles_for_rates_{county_slug}.csv")
    if os.path.exists(rates_file):
        try:
            df = pd.read_csv(rates_file)
            if 'default.electricity.kwh' in df.columns:
                annual_total = df['default.electricity.kwh'].sum()
                return float(annual_total)
        except Exception as e:
            print(f"Warning: Error reading {rates_file}: {e}")
    
    # Last fallback: combined profiles file
    combined_file = os.path.join(county_dir, f"combined_profiles_{scenario}_{county_slug}.csv")
    if os.path.exists(combined_file):
        try:
            df = pd.read_csv(combined_file)
            if 'electricity.real_and_simulated.for_typical_county_home.kwh' in df.columns:
                annual_total = df['electricity.real_and_simulated.for_typical_county_home.kwh'].sum()
                return float(annual_total)
        except Exception as e:
            print(f"Warning: Error reading {combined_file}: {e}")
    
    print(f"Warning: Could not find total consumption data for {county_slug} in scenario {scenario}")
    return 0.0


def load_battery_energy_data(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str
) -> float:
    """
    Load annual energy supported by battery (discharged to load).
    Returns annual kWh discharged from battery to load.
    """
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    
    # Try to find SAM optimized load profiles file
    sam_file_patterns = [
        f"solar_storage_dispatch_profiles_{county_slug}.csv",
        f"solar_storage_dispatch_profiles_{scenario}_{county_slug}.csv"
    ]
    
    for pattern in sam_file_patterns:
        sam_file_path = os.path.join(county_dir, pattern)
        if os.path.exists(sam_file_path):
            try:
                df = pd.read_csv(sam_file_path)
                if 'Battery to Load' in df.columns:
                    # Sum hourly values to get annual kWh
                    annual_battery_energy = df['Battery to Load'].sum()
                    return float(annual_battery_energy)
            except Exception as e:
                print(f"Warning: Error reading {sam_file_path}: {e}")
                continue
    
    print(f"Warning: Could not find battery energy data for {county_slug} in scenario {scenario}")
    return 0.0


def load_solar_energy_data(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str
) -> float:
    """
    Load annual energy supported by solar (directly to load, not including battery charging).
    Returns annual kWh from solar directly to load.
    """
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    
    # Try to find SAM optimized load profiles file
    sam_file_patterns = [
        f"solar_storage_dispatch_profiles_{county_slug}.csv",
        f"solar_storage_dispatch_profiles_{scenario}_{county_slug}.csv"
    ]
    
    for pattern in sam_file_patterns:
        sam_file_path = os.path.join(county_dir, pattern)
        if os.path.exists(sam_file_path):
            try:
                df = pd.read_csv(sam_file_path)
                if 'System to Load' in df.columns:
                    # Sum hourly values to get annual kWh
                    annual_solar_energy = df['System to Load'].sum()
                    return float(annual_solar_energy)
            except Exception as e:
                print(f"Warning: Error reading {sam_file_path}: {e}")
                continue
    
    # Fallback: try to get total solar generation from PV system if available
    # This would be total solar generation, not just direct to load
    try:
        # Look for solar generation files
        sam_results_dir = os.path.join(county_dir, "results", "solarstorage")
        if os.path.exists(sam_results_dir):
            # Try to find latest solar generation file
            for file in os.listdir(sam_results_dir):
                if file.startswith("RESULTS_solar_generation_") and file.endswith(".csv"):
                    solar_file_path = os.path.join(sam_results_dir, file)
                    df = pd.read_csv(solar_file_path)
                    # Look for solar generation column
                    for col in df.columns:
                        if 'solar' in col.lower() and 'generation' in col.lower():
                            return float(df[col].iloc[0]) if len(df) > 0 else 0.0
    except Exception as e:
        pass
    
    print(f"Warning: Could not find solar energy data for {county_slug} in scenario {scenario}")
    return 0.0


def load_sam_metric_data(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
    metric_column: str
) -> float:
    """
    Load annual data for any SAM load profile metric.
    Returns annual kWh sum for the specified metric column.
    """
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    
    # Try to find SAM optimized load profiles file
    sam_file_patterns = [
        f"solar_storage_dispatch_profiles_{county_slug}.csv",
        f"solar_storage_dispatch_profiles_{scenario}_{county_slug}.csv"
    ]
    
    for pattern in sam_file_patterns:
        sam_file_path = os.path.join(county_dir, pattern)
        if os.path.exists(sam_file_path):
            try:
                df = pd.read_csv(sam_file_path)
                if metric_column in df.columns:
                    # Sum hourly values to get annual kWh
                    annual_value = df[metric_column].sum()
                    return float(annual_value)
            except Exception as e:
                print(f"Warning: Error reading {sam_file_path}: {e}")
                continue
    
    print(f"Warning: Could not find {metric_column} data for {county_slug} in scenario {scenario}")
    return 0.0


# Appliance breakdown and weekly/SOC chart helpers are provided via helpers


def create_appliance_html_table(appliance_data: dict, county_slug: str, scenario: str) -> str:
    """
    Create an HTML table showing appliance breakdown when charts are not available.
    Returns HTML table as string.
    """
    county_name = county_slug.replace('-', ' ').title()
    scenario_name = scenario.replace('_', ' ').title()
    
    if not appliance_data or "Data Not Available" in appliance_data:
        return f"""
        <div style="text-align: center; padding: 40px; border: 1px solid #ddd; border-radius: 8px;">
            <h3>{county_name} County - {scenario_name} Scenario</h3>
            <p>No appliance data available for this county</p>
        </div>
        """
    
    # Sort by consumption 
    total_kwh = sum(appliance_data.values())
    sorted_data = sorted(appliance_data.items(), key=lambda x: x[1], reverse=True)
    
    # Create HTML table
    table_rows = ""
    for category, kwh in sorted_data:
        percentage = (kwh / total_kwh) * 100 if total_kwh > 0 else 0
        table_rows += f"""
        <tr>
            <td style="text-align: left; padding: 8px; border-bottom: 1px solid #eee;">{category}</td>
            <td style="text-align: right; padding: 8px; border-bottom: 1px solid #eee;">{kwh:,.0f}</td>
            <td style="text-align: right; padding: 8px; border-bottom: 1px solid #eee;">{percentage:.1f}%</td>
        </tr>
        """
    
    return f"""
    <div style="border: 1px solid #ddd; border-radius: 8px; padding: 15px;">
        <h3 style="text-align: center; margin-bottom: 15px; color: #333;">
            {county_name} County - {scenario_name} Scenario
        </h3>
        <p style="text-align: center; margin-bottom: 15px; color: #666;">
            Electricity Consumption by End-Use (Electrified Only)<br>
            Total: {total_kwh:,.0f} kWh/year
        </p>
        <table style="width: 100%; border-collapse: collapse; font-family: Arial, sans-serif;">
            <thead>
                <tr style="background-color: #f5f5f5;">
                    <th style="text-align: left; padding: 12px; border-bottom: 2px solid #ddd;">End Use</th>
                    <th style="text-align: right; padding: 12px; border-bottom: 2px solid #ddd;">kWh/year</th>
                    <th style="text-align: right; padding: 12px; border-bottom: 2px solid #ddd;">%</th>
                </tr>
            </thead>
            <tbody>
                {table_rows}
            </tbody>
        </table>
    </div>
    """


def load_sam_metric_data(base_input_dir: str, scenario: str, housing_type: str, county_slug: str, metric_column: str) -> float:
    """
    Load annual SAM metric data for mapping visualization.
    Returns total annual value for the specified metric column.
    """
    sam_file = os.path.join(base_input_dir, scenario, housing_type, county_slug, f"solar_storage_dispatch_profiles_{county_slug}.csv")
    
    try:
        if not os.path.exists(sam_file):
            print(f"Warning: SAM file not found: {sam_file}")
            return 0.0
            
        df = pd.read_csv(sam_file)
        if metric_column not in df.columns:
            print(f"Warning: Column {metric_column} not found in {sam_file}")
            return 0.0
            
        annual_total = df[metric_column].sum()
        return float(annual_total)
        
    except Exception as e:
        print(f"Error loading SAM metric {metric_column} for {county_slug}: {e}")
        return 0.0


# Weekly SAM and battery SOC chart functions are provided via helpers


def create_single_map(base_input_dir: str, scenario: str, housing_type: str, counties: list, 
                     metric_name: str, data_loader_config: dict) -> folium.Map:
    """
    Create a single diagnostic map for a specific metric.
    """
    # Initialize California county boundaries
    gdf = initialize_map()
    
    # Filter to requested counties
    county_names = [county.replace(" County", "") for county in counties]
    gdf = gdf[gdf["NAME"].isin(county_names)].copy()
    
    # Initialize metric columns
    gdf[metric_name] = 0.0
    gdf[f"{metric_name}_fmt"] = "N/A"
    
    # Load data for each county
    for _, row in gdf.iterrows():
        county_name = row["NAME"]
        county_slug = slugify_county_name(f"{county_name} County")
        county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
        
        try:
            # Special handling for different metrics
            if metric_name == "Solar Size (kW)":
                metric_value = load_solar_data(base_input_dir, scenario, housing_type, county_slug)
                
            elif metric_name == "Total Energy Consumption (kWh, therms)":
                elec_kwh, gas_thm = load_energy_consumption_data(
                    base_input_dir, scenario, housing_type, county_slug
                )
                # Use kWh equivalent for color mapping
                metric_value = elec_kwh + gas_thm * 29.3
                # Display both values in tooltip with better formatting
                elec_fmt = f"{elec_kwh:,.0f}" if elec_kwh >= 1000 else f"{elec_kwh:.0f}"
                gas_fmt = f"{gas_thm:,.0f}" if gas_thm >= 1000 else f"{gas_thm:.0f}"
                pretty = f"{elec_fmt} kWh<br>{gas_fmt} therms"
                gdf.loc[gdf["NAME"] == county_name, f"{metric_name}_fmt"] = pretty

            elif metric_name == "Net Grid Consumption (kWh)":
                metric_value = load_net_grid_consumption_data(
                    base_input_dir, scenario, housing_type, county_slug
                )
                # Format as kWh with comma separators
                pretty = f"{to_decimal_number(metric_value)} kWh"
                gdf.loc[gdf["NAME"] == county_name, f"{metric_name}_fmt"] = pretty
                
            elif metric_name == "Total Electricity Consumption (kWh)":
                metric_value = load_total_consumption_data(
                    base_input_dir, scenario, housing_type, county_slug
                )
                # Format as kWh with comma separators
                pretty = f"{to_decimal_number(metric_value)} kWh"
                gdf.loc[gdf["NAME"] == county_name, f"{metric_name}_fmt"] = pretty
                
            elif metric_name == "Battery Energy (kWh)":
                metric_value = load_battery_energy_data(
                    base_input_dir, scenario, housing_type, county_slug
                )
                # Format as kWh with comma separators
                pretty = f"{to_decimal_number(metric_value)} kWh"
                gdf.loc[gdf["NAME"] == county_name, f"{metric_name}_fmt"] = pretty
                
            elif metric_name == "Solar Energy (kWh)":
                metric_value = load_solar_energy_data(
                    base_input_dir, scenario, housing_type, county_slug
                )
                # Format as kWh with comma separators
                pretty = f"{to_decimal_number(metric_value)} kWh"
                gdf.loc[gdf["NAME"] == county_name, f"{metric_name}_fmt"] = pretty
                
            elif metric_name == "Solar+Storage Annual Savings ($)":
                metric_value = load_solar_savings_data(
                    base_input_dir, scenario, housing_type, county_slug
                )
                # Format with appropriate sign (+ for savings, - for extra costs)
                pretty = format_currency_with_sign(metric_value)
                gdf.loc[gdf["NAME"] == county_name, f"{metric_name}_fmt"] = pretty
                
            elif metric_name == "Capital Costs, Net After Incentives ($)":
                metric_value = load_capital_costs_data(
                    base_input_dir, scenario, housing_type, county_slug
                )

                # Format as currency
                pretty = f"${to_decimal_number(abs(metric_value))}"
                gdf.loc[gdf["NAME"] == county_name, f"{metric_name}_fmt"] = pretty
                # Add a note field to show in tooltip clarifying definition
                gdf.loc[gdf["NAME"] == county_name, f"{metric_name}_note"] = (
                    "Net outlay with PV/Storage (full incentives)"
                )
                
            elif metric_name == "Payback Period (years)":
                metric_value = load_payback_period_data(
                    scenario, housing_type, county_slug
                )
                # Format as years with 1 decimal place
                if metric_value >= 100:
                    pretty = ">100 years"
                else:
                    pretty = f"{metric_value:.1f} years"
                gdf.loc[gdf["NAME"] == county_name, f"{metric_name}_fmt"] = pretty
                
            elif data_loader_config.get("capital_component"):
                comp = data_loader_config["capital_component"]
                metric_value = load_capital_component(
                    base_input_dir, scenario, housing_type, county_slug, comp
                )
                pretty = f"${to_decimal_number(abs(metric_value))}"
                gdf.loc[gdf["NAME"] == county_name, f"{metric_name}_fmt"] = pretty

            elif data_loader_config.get("effective_price"):
                metric_value = load_effective_electricity_price(
                    base_input_dir, scenario, housing_type, county_slug
                )
                pretty = f"${metric_value:.3f}/kWh"
                gdf.loc[gdf["NAME"] == county_name, f"{metric_name}_fmt"] = pretty

            elif data_loader_config.get("pv_cf"):
                metric_value = load_pv_capacity_factor(
                    base_input_dir, scenario, housing_type, county_slug
                )
                pretty = f"{metric_value*100:.1f}%"
                gdf.loc[gdf["NAME"] == county_name, f"{metric_name}_fmt"] = pretty

            elif data_loader_config.get("self_supply"):
                metric_value = load_self_supply_ratio(
                    base_input_dir, scenario, housing_type, county_slug
                )
                pretty = f"{metric_value*100:.1f}%"
                gdf.loc[gdf["NAME"] == county_name, f"{metric_name}_fmt"] = pretty

            elif data_loader_config.get("peak_share"):
                metric_value = load_peak_period_load_share(
                    base_input_dir, scenario, housing_type, county_slug
                )
                pretty = f"{metric_value*100:.1f}%"
                gdf.loc[gdf["NAME"] == county_name, f"{metric_name}_fmt"] = pretty

            elif data_loader_config.get("sam_metric"):
                # Handle SAM metrics using load_sam_metric_data
                metric_column_map = {
                    "Load Profile (kWh)": "Load Profile",
                    "System to Load (kWh)": "System to Load", 
                    "Battery to Load (kWh)": "Battery to Load",
                    "Grid to Load (kWh)": "Grid to Load",
                    "Solar + Battery to Load (kWh)": "Solar + Battery to Load"
                }
                column_name = metric_column_map.get(metric_name)
                if column_name:
                    metric_value = load_sam_metric_data(
                        base_input_dir, scenario, housing_type, county_slug, column_name
                    )
                    # Format as kWh with comma separators
                    pretty = f"{to_decimal_number(metric_value)} kWh"
                    gdf.loc[gdf["NAME"] == county_name, f"{metric_name}_fmt"] = pretty
                else:
                    metric_value = 0.0
                    
            else:
                # Use load_cost_data to get metric data
                data = load_cost_data(
                    county_dir=county_dir,
                    subfolder=data_loader_config["subfolder"],
                    prefix=data_loader_config["prefix"],
                    scenario_row=data_loader_config["scenario_row"]
                )
                metric_value = float(data[data_loader_config["column"]])
            
            gdf.loc[gdf["NAME"] == county_name, metric_name] = metric_value
            
            # Only format if not already formatted (for energy consumption)
            if gdf.loc[gdf["NAME"] == county_name, f"{metric_name}_fmt"].iloc[0] == "N/A":
                gdf.loc[gdf["NAME"] == county_name, f"{metric_name}_fmt"] = to_decimal_number(metric_value)
            
        except Exception as e:
            print(f"Warning: Could not load {metric_name} data for {county_name}: {e}")
    
    m = folium.Map(
        location=[37.8, -120], 
        zoom_start=6, 
        zoom_control=False,
        width="450px", 
        height="350px"
    )
    
    # Add choropleth layer with error handling for bin issues
    try:
        add_choropleth_layer(
            m, gdf, metric_name,
            fill_color=data_loader_config["color_scheme"],
            bins=data_loader_config["bins"],
            legend_name=f"{metric_name} ({data_loader_config['unit']})"
        )
    except ValueError as e:
        if "All values are expected to fall into one of the provided bins" in str(e):
            # Debug: Print values outside bins
            values = gdf[metric_name].dropna()
            bins = data_loader_config["bins"]
            min_bin, max_bin = min(bins), max(bins)
            
            outside_values = values[(values < min_bin) | (values > max_bin)]
            
            print(f"\nERROR: Values outside bins for {metric_name}")
            print(f"Bins: {bins}")
            print(f"Bin range: {min_bin} to {max_bin}")
            print(f"Data range: {values.min():.2f} to {values.max():.2f}")
            print(f"Values outside bins ({len(outside_values)} total):")
            
            for idx, val in outside_values.items():
                county_name = gdf.loc[idx, "NAME"]
                print(f"  {county_name}: {val:.2f}")
            
            # Suggest new bins
            data_min, data_max = values.min(), values.max()
            suggested_min = min(min_bin, data_min * 0.9)  # 10% buffer below
            suggested_max = max(max_bin, data_max * 1.1)  # 10% buffer above
            print(f"\nSuggested bin range: {suggested_min:.0f} to {suggested_max:.0f}")
            
        raise e
    
    # Add county labels
    add_centroid_labels(m, gdf, metric_name)
    
    # Add tooltip layer (with extra note for capital net outlay metric)
    if metric_name == "Capital Costs, Net After Incentives ($)":
        # Ensure note column exists for all rows to avoid KeyError
        if f"{metric_name}_note" not in gdf.columns:
            gdf[f"{metric_name}_note"] = "Net outlay with PV/Storage (full incentives)"
        tooltip = folium.GeoJsonTooltip(
            fields=["NAME", f"{metric_name}_fmt", f"{metric_name}_note"],
            aliases=["County:", f"{metric_name}:", "Note:"],
            localize=True
        )
    else:
        tooltip = folium.GeoJsonTooltip(
            fields=["NAME", f"{metric_name}_fmt"],
            aliases=["County:", f"{metric_name}:"],
            localize=True
        )
    
    folium.GeoJson(
        gdf,
        style_function=lambda feature: {
            "fillColor": "transparent",
            "color": "black",
            "weight": 1,
            "fillOpacity": 0
        },
        tooltip=tooltip,
        name="County Info"
    ).add_to(m)
    
    return m


def create_appliance_breakdown_report(base_input_dir: str, scenario: str, housing_type: str, counties: list):
    """
    Create a standalone HTML report with appliance breakdown charts for all counties.
    """
    scenario_title = scenario.replace('_', ' ').title()
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Appliance Breakdown Report - {scenario_title}</title>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 20px;
                background-color: #f5f5f5;
            }}
            .header {{
                text-align: center;
                margin-bottom: 30px;
                background-color: white;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            .charts-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
                gap: 20px;
                max-width: 1400px;
                margin: 0 auto;
            }}
            .chart-container {{
                background-color: white;
                border-radius: 8px;
                padding: 15px;
                text-align: center;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            .chart-title {{
                font-size: 16px;
                font-weight: bold;
                margin-bottom: 10px;
                color: #333;
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>Appliance Energy Consumption Breakdown</h1>
            <h2>{scenario_title} - {housing_type.replace('-', ' ').title()}</h2>
            <p>Annual energy consumption by end-use category for California counties</p>
        </div>
        
        <div class="charts-grid">
    """
    
    # Generate charts for all counties
    county_names = [county.replace(" County", "") for county in counties]
    for county_name in county_names:
        county_slug = slugify_county_name(f"{county_name} County")
        
        try:
            chart_data = create_appliance_breakdown_chart(base_input_dir, scenario, housing_type, county_slug)
            
            # Check if it's base64 image data or HTML table
            if chart_data.startswith('<div'):
                # It's an HTML table
                html_content += f"""
                    <div class="chart-container">
                        {chart_data}
                    </div>
                """
            else:
                # It's base64 image data
                html_content += f"""
                    <div class="chart-container">
                        <div class="chart-title">{county_name} County</div>
                        <img src="data:image/png;base64,{chart_data}" alt="Appliance breakdown for {county_name}" style="max-width: 100%; height: auto;">
                    </div>
                """
        except Exception as e:
            print(f"Error creating appliance chart for {county_name}: {e}")
    
    html_content += """
        </div>
    </body>
    </html>
    """
    
    # Save the report
    output_dir = os.path.join("visualizations", "appliance_breakdown", "html")
    os.makedirs(output_dir, exist_ok=True)
    
    # Append git short SHA for versioning
    filename = (
        f"appliance_breakdown_{scenario}_{housing_type.replace(' ', '-').lower()}"
        f"_g{GIT_SHORT_SHA}.html"
    )
    output_path = os.path.join(output_dir, filename)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"Appliance breakdown report saved to: {output_path}")


def create_combined_dashboard(base_input_dir: str, scenario: str, housing_type: str, counties: list):
    """
    Create a combined HTML dashboard with diagnostic maps for key electrification metrics.
    """
    
    # Define metrics configuration
    metrics_config = {
        "Solar Size (kW)": {
            "color_scheme": "YlOrBr",
            "bins": SOLAR_SIZE_BINS,
            "unit": "kW"
        },
        "Total Energy Consumption (kWh, therms)": {
            "color_scheme": "Greens",
            "bins": ENERGY_CONSUMPTION_BINS,
            "unit": "kWh equiv."
        },
        "Total Electricity Consumption (kWh)": {
            "color_scheme": "Blues",
            "bins": TOTAL_ELECTRICITY_CONSUMPTION_BINS,
            "unit": "kWh"
        },
        "Net Grid Consumption (kWh)": {
            "color_scheme": "Reds",
            "bins": NET_GRID_CONSUMPTION_BINS,
            "unit": "kWh"
        },
        "Battery Energy (kWh)": {
            "color_scheme": "Purples",
            "bins": BATTERY_ENERGY_BINS,
            "unit": "kWh"
        },
        "Solar Energy (kWh)": {
            "color_scheme": "Oranges",
            "bins": SOLAR_ENERGY_BINS,
            "unit": "kWh"
        },
        "Annual Electricity Bill ($)": {
            "subfolder": "electricity",
            "prefix": "RESULTS_electricity_annual_costs",
            "column": "electricity.PG&E.E-TOU-D",
            "scenario_row": 0,
            "color_scheme": "Reds",
            "bins": [0, 1000, 2000, 3000, 4000, 5000, 6000, 8000, 10000],
            "unit": "$"
        },
        "Annual Gas Bill ($)": {
            "subfolder": "gas",
            "prefix": "RESULTS_gas_annual_costs",
            "column": "gas.PG&E.G-1",
            "scenario_row": 0,
            "color_scheme": "Oranges",
            "bins": [0, 500, 1000, 1500, 2000, 2500, 3000, 4000],
            "unit": "$"
        },
        "Solar+Storage Annual Savings ($)": {
            "color_scheme": "RdYlGn",
            "bins": [-2000, -1000, -500, 0, 500, 1000, 1500, 2000, 3000],
            "unit": "$"
        },
        "Capital Costs, Net After Incentives ($)": {
            "color_scheme": "Blues",
            "bins": [-1000, 0, 5000, 10000, 15000, 20000, 25000, 30000, 40000, 50000, 100000],
            "unit": "$"
        },
        "Payback Period (years)": {
            "color_scheme": "RdYlGn_r",
            "bins": PAYBACK_PERIOD_BINS,
            "unit": "years"
        },
        "Load Profile (kWh)": {
            "color_scheme": "Blues",
            "bins": [0, 2000, 4000, 6000, 8000, 10000, 12000, 14000, 16000],
            "unit": "kWh",
            "sam_metric": True
        },
        "System to Load (kWh)": {
            "color_scheme": "Oranges", 
            "bins": [0, 2000, 4000, 6000, 8000, 10000, 12000, 14000, 16000],
            "unit": "kWh",
            "sam_metric": True
        },
        "Battery to Load (kWh)": {
            "color_scheme": "Purples",
            "bins": [0, 500, 1000, 1500, 2000, 2500, 3000, 4000, 5000],
            "unit": "kWh",
            "sam_metric": True
        },
        "Grid to Load (kWh)": {
            "color_scheme": "Reds",
            "bins": [0, 2000, 4000, 6000, 8000, 10000, 12000, 14000, 16000],
            "unit": "kWh",
            "sam_metric": True
        },
        "Solar + Battery to Load (kWh)": {
            "color_scheme": "Greens",
            "bins": [0, 2000, 4000, 6000, 8000, 10000, 12000, 14000, 16000],
            "unit": "kWh",
            "sam_metric": True
        },
        # New diagnostics
        "PV Capex ($)": {
            "color_scheme": "Blues",
            "bins": [0, 2000, 4000, 6000, 8000, 10000, 15000, 20000, 30000],
            "unit": "$",
            "capital_component": "pv_capex"
        },
        "Storage Capex ($)": {
            "color_scheme": "Blues",
            "bins": [0, 2000, 4000, 6000, 8000, 10000, 15000, 20000, 30000],
            "unit": "$",
            "capital_component": "storage_capex"
        },
        "PV Incentives (Full) ($)": {
            "color_scheme": "Greens",
            "bins": [0, 500, 1000, 2000, 3000, 4000, 6000, 8000, 12000],
            "unit": "$",
            "capital_component": "pv_incentives_full"
        },
        "Storage Incentives (Full) ($)": {
            "color_scheme": "Greens",
            "bins": [0, 500, 1000, 2000, 3000, 4000, 6000, 8000, 12000],
            "unit": "$",
            "capital_component": "storage_incentives_full"
        },
        "PV+Storage Net (Full) ($)": {
            "color_scheme": "Purples",
            "bins": [0, 2000, 5000, 8000, 12000, 16000, 20000, 30000, 50000],
            "unit": "$",
            "capital_component": "pv_storage_net_full"
        },
        "Effective Electricity Price ($/kWh)": {
            "color_scheme": "OrRd",
            "bins": [0, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.75],
            "unit": "$/kWh",
            "effective_price": True
        },
        "PV Capacity Factor": {
            "color_scheme": "YlGn",
            "bins": [0.0, 0.10, 0.15, 0.18, 0.20, 0.22, 0.24, 0.28, 0.32],
            "unit": "fraction",
            "pv_cf": True
        },
        "Self-Supply Ratio": {
            "color_scheme": "PuBuGn",
            "bins": [0.0, 0.20, 0.40, 0.55, 0.70, 0.80, 0.88, 0.94, 1.0],
            "unit": "fraction",
            "self_supply": True
        },
        "Peak-Period Load Share": {
            "color_scheme": "PuRd",
            "bins": [0.0, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.45, 0.60],
            "unit": "fraction",
            "peak_share": True
        },
    }
    
    # Create individual maps
    maps = {}
    for metric_name, config in metrics_config.items():
        print(f"Creating map for: {metric_name}")
        try:
            maps[metric_name] = create_single_map(
                base_input_dir, scenario, housing_type, counties, metric_name, config
            )
        except Exception as e:
            print(f"Error creating map for {metric_name}: {e}")
    
    # Create the combined HTML
    scenario_title = scenario.replace('_', ' ').title()
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Diagnostic Maps - {scenario_title}</title>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 20px;
                background-color: #f5f5f5;
            }}
            .header {{
                text-align: center;
                margin-bottom: 30px;
                background-color: white;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            .dashboard {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(450px, 1fr));
                gap: 20px;
                max-width: 1400px;
                margin: 0 auto;
            }}
            .map-container {{
                background-color: white;
                border-radius: 8px;
                padding: 15px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            .map-title {{
                font-size: 16px;
                font-weight: bold;
                margin-bottom: 10px;
                text-align: center;
                color: #333;
            }}
            .map-wrapper {{
                display: flex;
                justify-content: center;
            }}
            /* Pruned unused chart styles (appliance, SOC, SAM weekly) */
        </style>
    </head>
    <body>
        <div class="header">
            <h1>Diagnostic Maps Dashboard</h1>
            <h2>{scenario_title} - {housing_type.replace('-', ' ').title()}</h2>
            <p>County-level analysis of key metrics for electrification scenario</p>
        </div>
        
        <div class="dashboard">
    """
    
    # Add each map to the HTML
    for i, (metric_name, map_obj) in enumerate(maps.items()):
        map_html = map_obj._repr_html_()
        html_content += f"""
            <div class="map-container">
                <div class="map-title">{metric_name}</div>
                <div class="map-wrapper">
                    {map_html}
                </div>
            </div>
        """
    
    # Close out the dashboard without additional chart sections; those live in Step 22 county dashboards
    html_content += """
        </div>
    </body>
    </html>
    """
    
    # Save the combined HTML file
    output_dir = os.path.join("visualizations", "diagnostic_maps", "html")
    os.makedirs(output_dir, exist_ok=True)

    # Append git short SHA for versioning
    filename = (
        f"diagnostic_dashboard_{scenario}_{housing_type.replace(' ', '-').lower()}"
        f"_g{GIT_SHORT_SHA}.html"
    )
    output_path = os.path.join(output_dir, filename)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    return output_path


def process(base_input_dir: str, base_output_dir: str, scenario: str, 
           housing_type: str, counties: list, desired_rate_plans: dict):
    """
    Display key metrics maps for the scenario in a combined dashboard.
    """
    
    log(
        at="step14_display_key_metrics_maps",
        info="starting_key_metrics_display",
        scenario=scenario,
        housing_type=housing_type,
        counties_requested=len(counties)
    )
    
    # Create combined dashboard
    try:
        dashboard_path = create_combined_dashboard(base_input_dir, scenario, housing_type, counties)
        
        # Also create standalone appliance breakdown report
        try:
            create_appliance_breakdown_report(base_input_dir, scenario, housing_type, counties)
            print(f"  - Created appliance breakdown report")
        except Exception as e:
            print(f"Warning: Could not create appliance breakdown report: {e}")
        
        # Auto-open in browser
        import webbrowser
        webbrowser.open(f'file://{os.path.abspath(dashboard_path)}')

        print(f"\nStep 16 complete! Created diagnostic dashboard:")
        print(f"  - File: {dashboard_path}")
        print(f"  - Opened in browser automatically")
        
        log(
            at="step14_display_key_metrics_maps",
            info="key_metrics_display_complete",
            scenario=scenario,
            housing_type=housing_type,
            counties_processed=len(counties),
            dashboard_path=dashboard_path
        )
        
        return [{"metric": "Combined Dashboard", "html_path": dashboard_path}]
        
    except Exception as e:
        print(f"Error creating dashboard: {e}")
        log(
            at="step14_display_key_metrics_maps",
            error=f"Failed to create dashboard: {e}",
            scenario=scenario
        )
        return []


def test_appliance_breakdown():
    """Test function to debug appliance breakdown functionality"""
    print("=" * 60)
    print("TESTING APPLIANCE BREAKDOWN FUNCTIONALITY")
    print("=" * 60)
    
    # Test scenarios and counties
    test_cases = [
        ("baseline", "alameda"),
        ("heat_pump_and_induction_stove", "alameda"),
        ("baseline", "los-angeles"),
        ("baseline", "san-diego")
    ]
    
    for scenario, county_slug in test_cases:
        print(f"\nTesting scenario: {scenario}, county: {county_slug}")
        print("-" * 40)
        
        data = load_appliance_breakdown_data(
            base_input_dir='data/loadprofiles',
            scenario=scenario,
            housing_type='single-family-detached',
            county_slug=county_slug
        )
        
        if data:
            print("SUCCESS: Found appliance data!")
            total_kwh = sum(data.values())
            print(f"Total consumption: {total_kwh:,.0f} kWh")
            for category, value in sorted(data.items(), key=lambda x: x[1], reverse=True):
                percentage = (value / total_kwh) * 100
                print(f"  {category}: {value:,.0f} kWh ({percentage:.1f}%)")
        else:
            print("FAILED: No appliance data found")
    
    print("\n" + "=" * 60)
    print("Creating test appliance breakdown report...")
    
    try:
        create_appliance_breakdown_report(
            base_input_dir='data/loadprofiles',
            scenario='baseline',
            housing_type='single-family-detached',
            counties=['Alameda County', 'Los Angeles County']
        )
        print("SUCCESS: Created appliance breakdown report")
    except Exception as e:
        print(f"FAILED: Could not create report: {e}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Display key metrics maps for electrification scenario")
    parser.add_argument("scenario", help="Electrification scenario to analyze (e.g., 'baseline', 'heat_pump', etc.)")
    parser.add_argument("--housing-type", default="single-family-detached", 
                       help="Housing type (default: single-family-detached)")
    parser.add_argument("--counties", nargs="+", default=norcal_counties + central_counties + socal_counties,
                       help="Counties to analyze (default: Alameda County)")
    parser.add_argument("--test-appliances", action="store_true",
                       help="Run appliance breakdown test instead of main process")
    
    args = parser.parse_args()
    
    if args.test_appliances:
        test_appliance_breakdown()
        exit()
    
    # Test configuration
    desired_rate_plans = {
        "PG&E": {"electricity": "E-TOU-D", "gas": "G-1"},
        "SCE": {"electricity": "TOU-D-4-9PM", "gas": "GR"},
        "SDG&E": {"electricity": "TOU-DR1", "gas": "GR"}
    }
    
    process(
        base_input_dir="data/loadprofiles",
        base_output_dir="data/loadprofiles",
        scenario=args.scenario,
        housing_type=args.housing_type,
        counties=args.counties,
        desired_rate_plans=desired_rate_plans
    )
