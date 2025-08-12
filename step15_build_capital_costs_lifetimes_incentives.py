"""
Step 15: Build Capital Costs, Lifetimes, Incentives

Build Capital Costs, Lifetimes, Incentives for my numbers.
Define each technology as a class that can be configured. It has a capital cost, 
a lifetime, and associated incentives at the state, federal, and utility level.

I want the ability to configure different Component "scenarios", like:
- No Incentives
- Half Incentives  
- My Capital Costs
- Cris's Capital Costs
- EMP Capital Costs
"""

import os
import pandas as pd
from main_helpers import log, slugify_county_name
from scenarios import SCENARIOS
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

class IncentiveScenario(Enum):
    """Defines different incentive scenarios for capital cost analysis."""
    FULL_INCENTIVES = "full_incentives"
    HALF_INCENTIVES = "half_incentives"
    NO_INCENTIVES = "no_incentives"

@dataclass
class Incentive:
    """Represents a single incentive (federal, state, or utility level)."""
    name: str
    value: float
    unit: str  # "$" for fixed amount, "%" for percentage
    max_value: Optional[float] = None
    description: str = ""
    source_url: str = ""


class ElectricAppliance(ABC):
    """Abstract base class for electric appliances used in home electrification."""
    
    def __init__(self, name: str, base_cost: float, lifetime_years: int):
        self.name = name
        self.base_cost = base_cost
        self.lifetime_years = lifetime_years
        self.incentives: List[Incentive] = []
    
    def add_incentive(self, incentive: Incentive) -> None:
        self.incentives.append(incentive)
    
    def calculate_total_incentives(self, scenario: IncentiveScenario = IncentiveScenario.FULL_INCENTIVES) -> float:
        if scenario == IncentiveScenario.NO_INCENTIVES:
            return 0.0
        
        total_incentives = 0.0
        multiplier = 1.0 if scenario == IncentiveScenario.FULL_INCENTIVES else 0.5
        
        for incentive in self.incentives:
            if incentive.unit == "%":
                incentive_value = self.base_cost * (incentive.value / 100)
                if incentive.max_value:
                    incentive_value = min(incentive_value, incentive.max_value)
            else:  # Fixed dollar amount
                incentive_value = incentive.value
            
            total_incentives += incentive_value * multiplier
        
        return total_incentives
    
    def get_net_cost(self, scenario: IncentiveScenario = IncentiveScenario.FULL_INCENTIVES) -> float:
        return max(0, self.base_cost - self.calculate_total_incentives(scenario))
    
    @abstractmethod
    def get_cost_breakdown(self, scenario: IncentiveScenario = IncentiveScenario.FULL_INCENTIVES) -> Dict:
        """Return detailed cost breakdown including incentives."""
        pass

from typing import Dict, Set

from typing import Dict, Set, Tuple

def diff_scenarios(
    scenario: str,
    base: str = "baseline",
)  -> dict[str, set[str]]:
    """
    Compare `scenario` with the `base` scenario (defaults to "baseline")
    and return two dictionaries:

        • electric_added  – end-uses that are electric in `scenario` but were
                            *not* electric in `base`  (includes gas→electric moves
                            *and* entirely new electric loads).

        • gas_removed     – end-uses that were gas in `base` and are *no longer*
                            gas in `scenario`  (i.e. converted to electric or
                            removed altogether).

    Example
    -------
    >>> e_added, g_removed = diff_scenarios("heat_pump")
    >>> e_added    # {'heating'}
    >>> g_removed  # {'heating'}
    """
    try:
        base_cfg   = SCENARIOS[base]
        target_cfg = SCENARIOS[scenario]
    except KeyError as err:
        raise ValueError(f"Unknown scenario '{err.args[0]}'") from None

    # --- convenience shortcuts -----------------------------------------
    base_elec   = base_cfg.get("electric", set())
    base_gas    = base_cfg.get("gas", set())
    target_elec = target_cfg.get("electric", set())
    target_gas  = target_cfg.get("gas", set())

    # --- what’s new on the electric side -------------------------------
    electric_added = target_elec - base_elec        # new or moved-from-gas

    # --- what’s vanished from the gas side -----------------------------
    gas_removed = base_gas - target_gas             # moved to electric or dropped

    return {"electric_added": electric_added, "gas_removed": gas_removed}

def net_outlay_by_scenario(
    electric: dict[str, "ElectricAppliance"],
    gas: dict[str, "ElectricAppliance"],
) -> dict[IncentiveScenario, float]:
    """
    Return a dict mapping each IncentiveScenario → summed net capital cost
    (electric - incentives) minus gas‐appliance capital cost.

    If the scenario does not replace a given gas appliance (e.g. induction stove
    when there was no gas stove), the gas cost is treated as 0.
    """
    gas_baseline = {name: app.base_cost for name, app in gas.items()}

    net_totals = defaultdict(float)         # {scenario: total $}

    for name, e_app in electric.items():
        gas_cost = gas_baseline.get(name, 0.0)

        for sc in (
            IncentiveScenario.FULL_INCENTIVES,
            IncentiveScenario.HALF_INCENTIVES,
            IncentiveScenario.NO_INCENTIVES,
        ):
            electric_net = e_app.get_net_cost(sc)
            net_totals[sc] += electric_net - gas_cost      # add difference

    return net_totals

def get_appliances_for_scenario(scenario: str) -> Dict[str, type]:
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario}. Available scenarios: {list(SCENARIOS.keys())}")
    
    diff = diff_scenarios(scenario)
    electric_appliances = diff["electric_added"]

    print(electric_appliances)
    
    appliance_classes = {}
    
    if "heating" in electric_appliances:
        from appliances.electric_heating import ElectricHeatingAppliance
        appliance_classes["heating"] = ElectricHeatingAppliance
    
    if "cooking" in electric_appliances:
        from appliances.electric_cooking import ElectricCookingAppliance
        appliance_classes["cooking"] = ElectricCookingAppliance
    
    if "hot_water" in electric_appliances:
        from appliances.electric_water_heating import ElectricWaterHeatingAppliance
        appliance_classes["hot_water"] = ElectricWaterHeatingAppliance
    
    if "vehicle_charging" in electric_appliances:
        from appliances.electric_vehicle import ElectricVehicleAppliance
        appliance_classes["vehicle"] = ElectricVehicleAppliance

    return appliance_classes


def get_gas_appliances_for_scenario(scenario: str) -> Dict[str, type]:
    """
    Determine which gas appliances are needed based on the scenario.
    
    Args:
        scenario: Scenario name from CostService.SCENARIOS
        
    Returns:
        Dictionary mapping appliance type to gas appliance class
    """
    
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario}. Available scenarios: {list(SCENARIOS.keys())}")
    
    diff = diff_scenarios(scenario)
    gas_appliances = diff["gas_removed"]

    print(gas_appliances)
    
    appliance_classes = {}
    
    if "heating" in gas_appliances:
        from appliances.gas_heating import GasHeatingAppliance
        appliance_classes["heating"] = GasHeatingAppliance
    
    if "cooking" in gas_appliances:
        from appliances.gas_stove import GasStoveAppliance
        appliance_classes["cooking"] = GasStoveAppliance
    
    if "vehicle_fuel" in gas_appliances:
        from appliances.ice_vehicle import ICEVehicleAppliance
        appliance_classes["vehicle"] = ICEVehicleAppliance

    return appliance_classes

def load_solar_capacity_data(base_input_dir: str, scenario: str, housing_type: str) -> dict:
    """
    Load solar capacity data for counties from electrified assets CSV.
    
    Args:
        base_input_dir: Base input directory
        scenario: Electrification scenario name
        housing_type: Housing type
        
    Returns:
        Dictionary mapping county slug to solar capacity in kW
    """
    try:
        from main_helpers import get_scenario_path
        from helpers.capital_costs_helper import load_electrified_assets
        
        scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
        assets_mapping = load_electrified_assets(scenario_path)
        
        # Convert county names to slugs for consistency
        slug_mapping = {}
        for county_name, solar_kw in assets_mapping.items():
            county_slug = slugify_county_name(county_name)
            slug_mapping[county_slug] = solar_kw
        
        print(f"Loaded solar capacity data: {len(slug_mapping)} counties")
        return slug_mapping
        
    except Exception as e:
        print(f"Warning: Could not load solar capacity data: {e}")
        return {}

def _save_capital_costs_to_csv(
    base_output_dir: str,
    scenario: str,
    housing_type: str,
    counties: list[str],
    electric_appliances: dict[str, "ElectricAppliance"],
    gas_appliances: dict[str, "ElectricAppliance"],
    incentive_scenarios: list[IncentiveScenario],
    solar_appliances: dict[str, "ElectricAppliance"] = None,
    storage_appliances: dict[str, "ElectricAppliance"] = None,
) -> None:
    """
    Write a single CSV with one row per county and the eight columns:

        county, capital_cost_full,
        incentives_full, incentives_half, incentives_none,
        net_outlay_full, net_outlay_half, net_outlay_none
    """
    rows: list[dict] = []
    
    # Default to empty dicts if solar/storage not provided
    solar_appliances = solar_appliances or {}
    storage_appliances = storage_appliances or {}

    for county in counties:
        # ----------------------------------------------------------
        # 1.  capital-cost buckets (no incentives applied yet)
        # ----------------------------------------------------------
        county_slug = slugify_county_name(county)
        
        capital_cost_electric = sum(app.base_cost for app in electric_appliances.values())
        capital_cost_gas      = sum(app.base_cost for app in gas_appliances.values())
        
        # Add solar/storage costs for this county if available
        capital_cost_solar = 0.0
        capital_cost_storage = 0.0
        if county_slug in solar_appliances:
            capital_cost_solar = solar_appliances[county_slug].base_cost
        if county_slug in storage_appliances:
            capital_cost_storage = storage_appliances[county_slug].base_cost
            
        total_capital_cost_electric = capital_cost_electric + capital_cost_solar + capital_cost_storage

        # ----------------------------------------------------------
        # 2.  incentives on the electric side (including solar/storage)
        # ----------------------------------------------------------
        incentives_full = sum(
            app.calculate_total_incentives(IncentiveScenario.FULL_INCENTIVES)
            for app in electric_appliances.values()
        )
        
        # Add solar/storage incentives for this county
        if county_slug in solar_appliances:
            incentives_full += solar_appliances[county_slug].calculate_total_incentives(IncentiveScenario.FULL_INCENTIVES)
        if county_slug in storage_appliances:
            incentives_full += storage_appliances[county_slug].calculate_total_incentives(IncentiveScenario.FULL_INCENTIVES)
        incentives_half = incentives_full * 0.5
        incentives_none = 0.0

        # ----------------------------------------------------------
        # 3.  incremental (“net”) outlay  = electric – gas – incentives
        # ----------------------------------------------------------
        net_outlay_full = (total_capital_cost_electric - capital_cost_gas) - incentives_full
        net_outlay_half = (total_capital_cost_electric - capital_cost_gas) - incentives_half
        net_outlay_none = (total_capital_cost_electric - capital_cost_gas)                # no incentives

        rows.append(
            {
                "county": county,
                "capital_cost_electric": capital_cost_electric,
                "capital_cost_solar": capital_cost_solar,
                "capital_cost_storage": capital_cost_storage,
                "total_capital_cost_electric": total_capital_cost_electric,
                "capital_cost_gas": capital_cost_gas,
                "incentives_full": incentives_full,
                "incentives_half": incentives_half,
                "incentives_none": incentives_none,
                "net_outlay_full": net_outlay_full,
                "net_outlay_half": net_outlay_half,
                "net_outlay_none": net_outlay_none,
            }
        )

    df = pd.DataFrame(rows).sort_values("county")

    out_dir = os.path.join(base_output_dir, "capital_costs")
    os.makedirs(out_dir, exist_ok=True)

    fname = f"capital_costs_summary_{scenario}_{housing_type.replace('-', '_')}.csv"
    csv_path = os.path.join(out_dir, fname)
    df.to_csv(csv_path, index=False)
    print(f"Capital-cost summary saved to: {csv_path}")

def _save_detailed_capital_costs_to_csv(
    base_output_dir: str,
    scenario: str,
    housing_type: str,
    counties: list[str],
    electric_appliances: dict[str, "ElectricAppliance"],
    gas_appliances: dict[str, "ElectricAppliance"],
    incentive_scenarios: list[IncentiveScenario],
    solar_appliances: dict[str, "ElectricAppliance"] = None,
    storage_appliances: dict[str, "ElectricAppliance"] = None,
) -> None:
    """
    Write detailed capital costs CSV file with individual appliance records for each county.
    This generates the format expected by step16_payback_periods.py.
    """
    rows = []
    
    # Default to empty dicts if solar/storage not provided
    solar_appliances = solar_appliances or {}
    storage_appliances = storage_appliances or {}
    
    for county in counties:
        county_slug = slugify_county_name(county)
        
        # Add records for each electric appliance
        for appliance_name, appliance in electric_appliances.items():
            for incentive_scenario in incentive_scenarios:
                breakdown = appliance.get_cost_breakdown(incentive_scenario)
                rows.append({
                    'county': county,
                    'county_slug': county_slug,
                    'scenario': scenario,
                    'housing_type': housing_type,
                    'appliance_category': 'electric',
                    'appliance_type': appliance_name,
                    'appliance_name': f"electric_{appliance_name}",
                    'incentive_scenario': incentive_scenario.value,
                    'base_cost': appliance.base_cost,
                    'total_incentives': appliance.calculate_total_incentives(incentive_scenario),
                    'net_cost': appliance.get_net_cost(incentive_scenario),
                    'lifetime_years': appliance.lifetime_years,
                    'cost_per_year': appliance.get_net_cost(incentive_scenario) / appliance.lifetime_years,
                    'annual_maintenance_cost': 0,
                    'annual_insurance_cost': 0,
                    'annual_fuel_cost': 0,
                    'annual_operating_cost': 0,
                    'total_operating_cost_over_lifetime': 0,
                    'total_cost_of_ownership': appliance.get_net_cost(incentive_scenario)
                })
        
        # Add records for solar appliance if available for this county
        if county_slug in solar_appliances:
            solar_appliance = solar_appliances[county_slug]
            for incentive_scenario in incentive_scenarios:
                breakdown = solar_appliance.get_cost_breakdown(incentive_scenario)
                rows.append({
                    'county': county,
                    'county_slug': county_slug,
                    'scenario': scenario,
                    'housing_type': housing_type,
                    'appliance_category': 'solar',
                    'appliance_type': 'solar_system',
                    'appliance_name': solar_appliance.name,
                    'incentive_scenario': incentive_scenario.value,
                    'base_cost': solar_appliance.base_cost,
                    'total_incentives': solar_appliance.calculate_total_incentives(incentive_scenario),
                    'net_cost': solar_appliance.get_net_cost(incentive_scenario),
                    'lifetime_years': solar_appliance.lifetime_years,
                    'cost_per_year': solar_appliance.get_net_cost(incentive_scenario) / solar_appliance.lifetime_years,
                    'annual_maintenance_cost': 0,
                    'annual_insurance_cost': 0,
                    'annual_fuel_cost': 0,
                    'annual_operating_cost': 0,
                    'total_operating_cost_over_lifetime': 0,
                    'total_cost_of_ownership': solar_appliance.get_net_cost(incentive_scenario)
                })
        
        # Add records for storage appliance if available for this county
        if county_slug in storage_appliances:
            storage_appliance = storage_appliances[county_slug]
            for incentive_scenario in incentive_scenarios:
                breakdown = storage_appliance.get_cost_breakdown(incentive_scenario)
                rows.append({
                    'county': county,
                    'county_slug': county_slug,
                    'scenario': scenario,
                    'housing_type': housing_type,
                    'appliance_category': 'storage',
                    'appliance_type': 'battery_storage',
                    'appliance_name': storage_appliance.name,
                    'incentive_scenario': incentive_scenario.value,
                    'base_cost': storage_appliance.base_cost,
                    'total_incentives': storage_appliance.calculate_total_incentives(incentive_scenario),
                    'net_cost': storage_appliance.get_net_cost(incentive_scenario),
                    'lifetime_years': storage_appliance.lifetime_years,
                    'cost_per_year': storage_appliance.get_net_cost(incentive_scenario) / storage_appliance.lifetime_years,
                    'annual_maintenance_cost': 0,
                    'annual_insurance_cost': 0,
                    'annual_fuel_cost': 0,
                    'annual_operating_cost': 0,
                    'total_operating_cost_over_lifetime': 0,
                    'total_cost_of_ownership': storage_appliance.get_net_cost(incentive_scenario)
                })
    
    # Save detailed CSV
    detailed_df = pd.DataFrame(rows).sort_values(['county', 'appliance_type', 'incentive_scenario'])
    
    out_dir = os.path.join(base_output_dir, "capital_costs")
    os.makedirs(out_dir, exist_ok=True)
    
    fname = f"capital_costs_{scenario}_{housing_type.replace('-', '_')}.csv"
    detailed_csv_path = os.path.join(out_dir, fname)
    detailed_df.to_csv(detailed_csv_path, index=False)
    print(f"Detailed capital costs saved to: {detailed_csv_path}")

def initialize_capital_cost_appliances(
    scenario: str,
) -> Tuple[Dict[str, "ElectricAppliance"], Dict[str, "ElectricAppliance"]]:
    """
    Instantiate and return the electric_appliances and gas_appliances dicts
    required by `process`.

    Raises
    ------
    ValueError
        If `scenario` is not defined in SCENARIOS.
    """
    # look up which appliance classes the scenario requires
    electric_classes = get_appliances_for_scenario(scenario)
    gas_classes      = get_gas_appliances_for_scenario(scenario)

    electric: Dict[str, ElectricAppliance] = {}
    gas: Dict[str, ElectricAppliance]      = {}

    # ---------- electric ---------------------------------------------------
    if "heating" in electric_classes:
        electric["heating"] = electric_classes["heating"](
            heating_type="heat_pump",
            base_cost=19_000.0,
            lifetime_years=15,
        )

    if "cooking" in electric_classes:
        electric["cooking"] = electric_classes["cooking"](
            cooking_type="induction",
            base_cost=2_000.0,
            lifetime_years=15,
        )

    if "hot_water" in electric_classes:
        electric["hot_water"] = electric_classes["hot_water"](
            heater_type="heat_pump",
            base_cost=2_637.0,
            lifetime_years=15,
        )

    if "vehicle" in electric_classes:
        electric["vehicle"] = electric_classes["vehicle"](
            vehicle_type="Tesla_Model_3",
            base_cost=45_000.0,
            lifetime_years=12,
            annual_maintenance_cost=800.0,
            annual_insurance_cost=1_800.0,
        )

    # ---------- gas --------------------------------------------------------
    # TODO make sure the capital costs are net with gas, not absolute

    if "heating" in gas_classes:
        gas["heating"] = gas_classes["heating"](
            heating_type="furnace",
            base_cost=4_500.0,
            lifetime_years=15,
        )

    if "cooking" in gas_classes:
        gas["cooking"] = gas_classes["cooking"](
            stove_type="gas",
            base_cost=1_600.0,
            lifetime_years=15,
        )

    # TODO: Add a gas water heater too

    if "vehicle" in gas_classes:
        gas["vehicle"] = gas_classes["vehicle"](
            vehicle_type="ICE",
            base_cost=35_000.0,
            lifetime_years=12,
            annual_maintenance_cost=1_200.0,
            annual_insurance_cost=2_000.0,
        )

    return electric, gas

def process(
    base_input_dir: str,
    base_output_dir: str,
    scenario: str,
    housing_type: str,
    counties: list[str],
    include_solar_storage: bool = False,
):
    """Build capital-cost, lifetime, and incentive tables for a scenario."""
    log(
        at="step15_build_capital_costs_lifetimes_incentives",
        info="starting_capital_costs_build",
        scenario=scenario,
        housing_type=housing_type,
        include_solar_storage=include_solar_storage,
    )

    try:
        electric_appliances, gas_appliances = initialize_capital_cost_appliances(
            scenario
        )
    except ValueError as err:
        log(
            at="step15_build_capital_costs_lifetimes_incentives",
            info="capital_costs_build_failed",
            error=str(err),
        )
        return {}
        
    # Initialize solar and storage appliances if requested
    solar_appliances = {}
    storage_appliances = {}
    
    if include_solar_storage:
        try:
            # Load solar capacity data
            solar_capacity_data = load_solar_capacity_data(base_input_dir, scenario, housing_type)
            
            if solar_capacity_data:
                from appliances.solar_system import SolarSystemAppliance
                from appliances.battery_storage import BatteryStorageAppliance
                
                # Create solar and storage appliances for each county
                for county_slug, solar_kw in solar_capacity_data.items():
                    if solar_kw > 0:
                        solar_appliances[county_slug] = SolarSystemAppliance(
                            capacity_kw=solar_kw,
                            lifetime_years=25
                        )
                        # Add one Tesla Powerwall 3 per installation
                        storage_appliances[county_slug] = BatteryStorageAppliance(
                            num_units=1,
                            lifetime_years=15
                        )
                        
                print(f"Created solar/storage appliances for {len(solar_appliances)} counties")
            else:
                print("No solar capacity data found, skipping solar/storage appliances")
                
        except Exception as e:
            print(f"Warning: Could not initialize solar/storage appliances: {e}")
            include_solar_storage = False

    incentive_scenarios = [
        IncentiveScenario.FULL_INCENTIVES,
        IncentiveScenario.HALF_INCENTIVES,
        IncentiveScenario.NO_INCENTIVES,
    ]

    # (Optional) quick sanity-check / warm-up
    for app in electric_appliances.values():
        _ = [app.get_cost_breakdown(sc) for sc in incentive_scenarios]

    _save_capital_costs_to_csv(
        base_output_dir,
        scenario,
        housing_type,
        counties,
        electric_appliances,
        gas_appliances,
        incentive_scenarios,
        solar_appliances if include_solar_storage else None,
        storage_appliances if include_solar_storage else None,
    )
    
    # Also save detailed CSV format expected by step16_payback_periods.py
    _save_detailed_capital_costs_to_csv(
        base_output_dir,
        scenario,
        housing_type,
        counties,
        electric_appliances,
        gas_appliances,
        incentive_scenarios,
        solar_appliances if include_solar_storage else None,
        storage_appliances if include_solar_storage else None,
    )

    all_appliances = {**electric_appliances, **gas_appliances}
    if include_solar_storage:
        all_appliances.update({f"solar_{k}": v for k, v in solar_appliances.items()})
        all_appliances.update({f"storage_{k}": v for k, v in storage_appliances.items()})
        
    log(
        at="step15_build_capital_costs_lifetimes_incentives",
        info="capital_costs_build_completed",
        electric_appliances_initialized=len(electric_appliances),
        gas_appliances_initialized=len(gas_appliances),
        solar_appliances_initialized=len(solar_appliances) if include_solar_storage else 0,
        storage_appliances_initialized=len(storage_appliances) if include_solar_storage else 0,
        total_appliances_initialized=len(all_appliances),
        scenarios_evaluated=len(incentive_scenarios),
    )

    result = {"electric": electric_appliances, "gas": gas_appliances}
    if include_solar_storage:
        result.update({
            "solar": solar_appliances,
            "storage": storage_appliances
        })
    return result

if __name__ == "__main__":
    import argparse
    from scenarios import SCENARIOS
    from main_helpers import norcal_counties, socal_counties, central_counties
    
    parser = argparse.ArgumentParser(description="Build capital costs, lifetimes, and incentives for electrification scenarios")
    parser.add_argument("scenario", 
                       choices=list(SCENARIOS.keys()),
                       help="Electrification scenario to analyze")
    parser.add_argument("--include-solar-storage", action="store_true",
                       help="Include solar and storage capital costs based on electrified_assets.csv")
    
    args = parser.parse_args()
    
    housing_type = "single-family-detached"
    all_counties = norcal_counties + socal_counties + central_counties
    
    result = process(
        base_input_dir="data/loadprofiles",
        base_output_dir="data/loadprofiles", 
        scenario=args.scenario,
        housing_type=housing_type,
        counties=all_counties,
        include_solar_storage=args.include_solar_storage
    )
    
