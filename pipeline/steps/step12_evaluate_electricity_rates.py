# establish a mapping of IOUs to counties
# look up each county and find their IOU
# calculate their annual electricity bill based on tarrifs
# save one file for each county for average daily, monthly, and annual bills
# also save the average electricity consumption for daily, monthly, and annual (this will be useful for solar+storage capital costs via tesla later)

# Baseline Allowance per Territory and Season
# https://www.pge.com/en/account/rate-plans/how-rates-work/baseline-allowance.html#accordion-2fb51186db-item-2ea52b55e4
# Baseline Allowances for E-TOU-C Rate Plan

import argparse
import os
import pandas as pd
from collections import defaultdict
from datetime import datetime, timedelta
from helpers.main_helpers import get_counties, get_scenario_path, log, to_number, get_timestamp, norcal_counties, socal_counties, central_counties, slugify_county_name
from helpers.electricity_rate_helpers import PGE_RATE_PLANS, SCE_RATE_PLANS, SDGE_RATE_PLANS
from helpers.utility_helpers import get_utility_for_county
from tariffs import EnergyFlows, NBTScenario, TariffCatalog, calculate_nbt_bill, required_nbt_import_plan
from tariffs.calendar import calendarize_full_year


RATE_PLANS = {
    "PG&E": PGE_RATE_PLANS,
    "SCE": SCE_RATE_PLANS,
    "SDG&E": SDGE_RATE_PLANS,
}

INPUT_FILE_NAME = "loadprofiles_for_rates"
OUTPUT_FILE_NAME = "RESULTS_electricity_annual_costs"

LOAD_FOR_RATE_ELECTRICITY_COLUMN = ".electricity.kwh"

def get_season(hour_index):
    start_date = datetime(year=2018, month=1, day=1)  # Consistent with NREL inputs
    current_datetime = start_date + timedelta(hours=hour_index)
    month = current_datetime.month
    return 'summer' if 6 <= month <= 9 else 'winter'


def is_weekend(dt):
    return dt.weekday() >= 5

def select_rate_section(plan_details, season, dt):
    """
    Given a rate plan's details and a season (e.g., "summer" or "winter"),
    select and return the rate section that applies for the given datetime dt.
    
    If the season's rates are divided into day types (e.g., "weekdays" and "weekend"),
    this function returns the corresponding sub-dictionary; otherwise, it returns
    the season's flat rate configuration.
    """
    season_rates = plan_details.get(season)
    if not season_rates:
        return None

    if "weekdays" in season_rates or "weekends" in season_rates:
        return season_rates.get("weekends") if is_weekend(dt) else season_rates.get("weekdays")
    return season_rates

def get_hourly_rate(rate_section, hour):
    if "peakHours" in rate_section and hour in rate_section["peakHours"]:
        return rate_section["peak"]
    elif "partPeakHours" in rate_section and hour in rate_section["partPeakHours"]:
        return rate_section["partPeak"]
    elif "superOffPeakHours" in rate_section and hour in rate_section["superOffPeakHours"]:
        return rate_section["superOffPeak"]
    else:
        return rate_section["offPeak"]

# TODO: Implement minimum daily charge, baseline credits
def calculate_annual_costs_electricity(load_profile, utility, rate_plan_name, timestamps=None):
    """Calculate a comparison-plan retail bill with strict hourly rate lookup.

    A missing ``fixedCharge`` explicitly means that the comparison plan has no
    daily fixed charge. Missing seasons, day types, or energy rates are errors.
    """
    annual_costs = defaultdict(float)
    try:
        plan_details = RATE_PLANS[utility][rate_plan_name]
    except KeyError as exc:
        raise KeyError(f"Unknown retail plan {utility} {rate_plan_name}") from exc

    if timestamps is not None and len(timestamps) != len(load_profile):
        raise ValueError(
            f"timestamps and load_profile must have the same length; got "
            f"{len(timestamps)} and {len(load_profile)}"
        )

    for hour_index, hourly_load in enumerate(load_profile):
        if timestamps is not None:
            current_datetime = pd.Timestamp(timestamps[hour_index]).to_pydatetime()
        else:
            current_datetime = datetime(year=2018, month=1, day=1) + timedelta(hours=hour_index)
        season = 'summer' if 6 <= current_datetime.month <= 9 else 'winter'
        day_type = "weekends" if is_weekend(current_datetime) else "weekdays"
        season_rates = plan_details.get(season)
        if season_rates is None:
            raise KeyError(f"Missing {season} rates for {utility} {rate_plan_name}")
        if day_type in season_rates:
            day_rates = season_rates[day_type]
        elif "weekdays" in season_rates or "weekends" in season_rates:
            raise KeyError(f"Missing {day_type} rates for {utility} {rate_plan_name} {season}")
        else:
            day_rates = season_rates

        rate = _hourly_import_rate(plan_details, current_datetime)

        # Calculate the cost for the hour
        energy_cost = hourly_load * rate
        annual_costs[rate_plan_name] += energy_cost

        # An absent fixedCharge is an explicit zero for comparison plans.
        fixed_charge = float(day_rates["fixedCharge"]) if "fixedCharge" in day_rates else 0.0
        annual_costs[rate_plan_name] += fixed_charge / 24

    return annual_costs


def _hourly_import_rate(plan_details, dt: datetime) -> float:
    """Return the import rate ($/kWh) for a given datetime.

    BUG HISTORY (fixed 2026-03-03, same root cause as step9b_cooptimize_core.py):
        Used 'weekend' (singular) instead of 'weekends' (plural). Silent fallback
        returned 0.0 for all weekend hours across all rate plans.
    """
    season = 'summer' if 6 <= dt.month <= 9 else 'winter'
    season_rates = plan_details.get(season)
    if not season_rates:
        raise KeyError(
            f"Season '{season}' not found in rate plan. "
            f"Available keys: {list(plan_details.keys())}"
        )

    day_type = 'weekends' if is_weekend(dt) else 'weekdays'
    if day_type in season_rates:
        day_rates = season_rates[day_type]
    elif 'weekdays' in season_rates or 'weekends' in season_rates:
        raise KeyError(
            f"Rate plan has a weekday/weekend split but '{day_type}' key not found. "
            f"Available keys in '{season}': {list(season_rates.keys())}. "
            f"Check for 'weekdays'/'weekends' key name typos in electricity_rate_helpers.py."
        )
    else:
        day_rates = season_rates

    h = dt.hour
    if 'peakHours' in day_rates and h in day_rates['peakHours']:
        return float(day_rates['peak'])
    if 'onPeakHours' in day_rates and h in day_rates['onPeakHours']:
        return float(day_rates['onPeak'])
    if 'midPeakHours' in day_rates and h in day_rates['midPeakHours']:
        return float(day_rates['midPeak'])
    if 'partPeakHours' in day_rates and h in day_rates['partPeakHours']:
        return float(day_rates['partPeak'])
    if 'superOffPeakHours' in day_rates and h in day_rates['superOffPeakHours']:
        return float(day_rates['superOffPeak'])
    if 'offPeak' in day_rates:
        return float(day_rates['offPeak'])
    if 'peak' in day_rates:
        return float(day_rates['peak'])
    raise KeyError(
        f"No fallback rate key ('offPeak' or 'peak') found in {day_type}/{season} "
        f"rates at hour {h}. Available keys: {list(day_rates.keys())}"
    )


def process_county_scenario_from_series(file_path, county, utility, selected_rate_plan, column_name):
    """Read a specific aggregator column and compute retail annual cost for the given plan."""
    file = os.path.join(file_path, county, f"{INPUT_FILE_NAME}_{county}.csv")
    if not os.path.exists(file):
        raise FileNotFoundError(f"File not found: {file}")
    cols = [column_name]
    if 'timestamp' not in cols:
        cols = ['timestamp', column_name]
    df = pd.read_csv(file, usecols=cols)
    load_profile = df[column_name].astype(float).tolist()
    timestamps = pd.to_datetime(df['timestamp']).values if 'timestamp' in df.columns else None
    return calculate_annual_costs_electricity(load_profile, utility, selected_rate_plan, timestamps=timestamps)


def nbt_ledger_for_county(
    file_path,
    county,
    utility,
    selected_rate_plan,
    *,
    nbt_scenario: NBTScenario | None = None,
    nbc_dollars_per_kwh_override=None,
):
    """Compute the full monthly NBT ledger for one county and import plan.

    Returns the whole `BillLedger` rather than just the annual total so callers
    can also report the credit-bank diagnostics (see `unused_credit`), which
    are what expose Step 9b's marginal-credit optimization over-valuing exports
    relative to this realized bill.
    """
    file = os.path.join(file_path, county, f"{INPUT_FILE_NAME}_{county}.csv")
    if not os.path.exists(file):
        raise FileNotFoundError(f"File not found: {file}")

    df = pd.read_csv(file)
    required_columns = {"timestamp", "nem3.imports.kwh", "nem3.exports.kwh"}
    missing = required_columns - set(df.columns)
    if missing:
        raise KeyError(f"{file} is missing required NBT columns: {sorted(missing)}")
    resolved_scenario = nbt_scenario or NBTScenario()
    source_timestamps = pd.DatetimeIndex(pd.to_datetime(df["timestamp"], errors="raise"))
    if set(source_timestamps.year) == {resolved_scenario.billing_year}:
        timestamps = source_timestamps
    else:
        timestamps = calendarize_full_year(source_timestamps, resolved_scenario.billing_year)
    imports_col = "nem3.imports.kwh"
    exports_col = "nem3.exports.kwh"
    tariff = TariffCatalog().bundle(
        utility,
        resolved_scenario,
        import_plan=selected_rate_plan,
        non_bypassable_rate=nbc_dollars_per_kwh_override,
    )
    return calculate_nbt_bill(
        EnergyFlows(
            timestamps=timestamps,
            import_kwh=df[imports_col].astype(float).tolist(),
            export_kwh=df[exports_col].astype(float).tolist(),
        ),
        tariff,
    )


def process_county_scenario_nem3(
    file_path,
    county,
    utility,
    selected_rate_plan,
    *,
    nbt_scenario: NBTScenario | None = None,
    nbc_dollars_per_kwh_override=None,
):
    """Compute an NBT bill from interval meter imports and exports."""
    ledger = nbt_ledger_for_county(
        file_path,
        county,
        utility,
        selected_rate_plan,
        nbt_scenario=nbt_scenario,
        nbc_dollars_per_kwh_override=nbc_dollars_per_kwh_override,
    )
    return {selected_rate_plan: ledger.annual_amount_due}

def build_results_df_with_variants(scenario: str, utility: str, *, retail_default: dict, retail_solar: dict, nem3_solar: dict | None = None) -> pd.DataFrame:
    """Return DataFrame with two rows (<scenario>, <scenario>.solarstorage) and columns per plan variant.

    Columns written in this order to preserve legacy behavior where downstream readers pick the first numeric column:
      1) electricity.<utility>.<plan>              (retail import)
      2) electricity.<utility>.<plan>_NEM3        (with NEM3 credits for .solarstorage row only)
    """
    plan_names = list(retail_default.keys())
    base_cols = [f"electricity.{utility}.{p}" for p in plan_names]
    nem3_cols = [f"electricity.{utility}.{p}_NEM3" for p in plan_names] if nem3_solar else []
    columns = base_cols + nem3_cols
    idx = [scenario, f"{scenario}.solarstorage"]
    df = pd.DataFrame(columns=columns, index=idx)

    # Default (no PV) retail
    for plan, cost in retail_default.items():
        df.loc[scenario, f"electricity.{utility}.{plan}"] = cost

    # Solar+storage retail imports (no export credits)
    for plan, cost in retail_solar.items():
        df.loc[f"{scenario}.solarstorage", f"electricity.{utility}.{plan}"] = cost

    # Solar+storage with NEM3 overlay (optional)
    if nem3_solar:
        for plan, cost in nem3_solar.items():
            df.loc[f"{scenario}.solarstorage", f"electricity.{utility}.{plan}_NEM3"] = cost

    return df

def get_output_file_path(base_output_dir, scenario, housing_type, county, timestamp):
    output_path = os.path.join(
        base_output_dir,
        scenario,
        housing_type,
        county,
        "results",
        "electricity",
        f"{OUTPUT_FILE_NAME}_{county}_{timestamp}.csv"
    )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    return output_path

def update_csv_with_results(output_file_path, results_df):
    """
    If an output CSV exists, update overlapping rows/columns with new results
    else, use the new dataframe
    """

    if os.path.exists(output_file_path):
        existing_df = pd.read_csv(output_file_path, index_col="scenario")

        for idx in results_df.index:
            for col in results_df.columns:
                existing_df.loc[idx, col] = results_df.loc[idx, col]
        return existing_df
    else:
        return results_df
    
def update_df_with_results(orig_df, new_df):
    """
    Update the original DataFrame with new results.
    """
    for idx in new_df.index:
        for col in new_df.columns:
            orig_df.loc[idx, col] = new_df.loc[idx, col]
    return orig_df

def utility_to_rate_plans(utility: str):
    match utility:
        case "PG&E":
            return PGE_RATE_PLANS
        case "SCE":
            return SCE_RATE_PLANS
        case "SDG&E":
            return SDGE_RATE_PLANS
        case _:
            raise ValueError(f"Unknown utility: {utility}")
    
def process(
    base_input_dir,
    base_output_dir,
    scenario,
    housing_type,
    counties,
    use_nem3: bool = True,
    *,
    nbc_dollars_per_kwh_override=None,
    nbt_scenario: NBTScenario | None = None,
):
    timestamp = get_timestamp()

    scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
    scenario_counties = get_counties(scenario_path, counties)

    for county in scenario_counties:
        results_df = pd.DataFrame()
        utility = get_utility_for_county(county)
        assert utility is not None, f"Utility not found for county: {county}"
        rate_plans = utility_to_rate_plans(utility)
        
        log_kwargs = {}
        for rate_plan in rate_plans:
            # Retail import-only costs
            retail_default = process_county_scenario_from_series(
                scenario_path, county, utility, rate_plan, "default.electricity.kwh"
            )
            retail_solar = process_county_scenario_from_series(
                scenario_path, county, utility, rate_plan, "retail.imports.kwh"
            )

            # NBT has one required highly differentiated import plan per IOU.
            # Other retail plans remain useful as non-NBT comparison cases.
            solar_nem3 = None
            nbt_ledger = None
            if use_nem3 and rate_plan == required_nbt_import_plan(utility):
                nbt_ledger = nbt_ledger_for_county(
                    scenario_path,
                    county,
                    utility,
                    rate_plan,
                    nbt_scenario=nbt_scenario,
                    nbc_dollars_per_kwh_override=nbc_dollars_per_kwh_override,
                )
                solar_nem3 = {rate_plan: nbt_ledger.annual_amount_due}

            annual_costs_results = build_results_df_with_variants(
                scenario,
                utility,
                retail_default=retail_default,
                retail_solar=retail_solar,
                nem3_solar=solar_nem3,
            )

            results_df = update_df_with_results(results_df, annual_costs_results)

            log_kwargs.update({
                f"annual_electricity_costs_{rate_plan}": to_number(retail_default[rate_plan]),
                f"annual_electricity_costs_solarstorage_{rate_plan}": to_number(retail_solar[rate_plan]),
            })
            if solar_nem3 is not None:
                log_kwargs[f"annual_electricity_costs_solarstorage_{rate_plan}_NEM3"] = to_number(
                    solar_nem3[rate_plan]
                )
            if nbt_ledger is not None:
                # Realized-bill counterpart to Step 9b's marginal export signal.
                # Unused credit is the wedge between the two; keep it visible.
                log_kwargs.update({
                    f"nbt_credit_earned_{rate_plan}": to_number(nbt_ledger.annual_credit_earned),
                    f"nbt_credit_applied_{rate_plan}": to_number(nbt_ledger.annual_credit_applied),
                    f"nbt_credit_unused_{rate_plan}": to_number(nbt_ledger.unused_credit),
                    f"nbt_credit_saturation_{rate_plan}": to_number(
                        nbt_ledger.credit_saturation_ratio
                    ),
                    f"nbt_expired_base_credit_{rate_plan}": to_number(
                        nbt_ledger.expired_base_credit
                    ),
                })

        output_file_path = get_output_file_path(base_output_dir, scenario, housing_type, county, timestamp)
        combined_df = update_csv_with_results(output_file_path, results_df)
        combined_df.to_csv(output_file_path, index_label="scenario")

        log(
            at="step12_evaluate_electricity_rates",
            county=county,
            utility=utility,
            **log_kwargs,
            saved_to=output_file_path,
        )

if __name__ == '__main__':
    p = argparse.ArgumentParser(description="Step 12: Evaluate electricity rates (with optional NEM 3.0)")
    p.add_argument("--base-input-dir", default="data/loadprofiles")
    p.add_argument("--base-output-dir", default="data/loadprofiles")
    p.add_argument("--scenario", default="baseline")
    p.add_argument("--housing-type", default="single-family-detached")
    p.add_argument("--counties", nargs="*", help="Counties (names or slugs). Use --all-counties to auto-discover.")
    p.add_argument("--all-counties", action="store_true")
    p.add_argument("--nem3", action="store_true", help="Enable NEM 3.0 export crediting for solar+storage rows")
    args = p.parse_args()

    if args.all_counties:
        scen_path = get_scenario_path(args.base_input_dir, args.scenario, args.housing_type)
        counties = get_counties(scen_path, None)
    else:
        counties = args.counties or ["Alameda County"]

    process(
        args.base_input_dir,
        args.base_output_dir,
        args.scenario,
        args.housing_type,
        counties,
        use_nem3=args.nem3,
    )
