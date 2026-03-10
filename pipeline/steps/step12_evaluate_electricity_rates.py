# establish a mapping of IOUs to counties
# look up each county and find their IOU
# calculate their annual electricity bill based on tarrifs
# save one file for each county for average daily, monthly, and annual bills
# also save the average electricity consumption for daily, monthly, and annual (this will be useful for solar+storage capital costs via tesla later)

# Baseline Allowance per Territory and Season
# https://www.pge.com/en/account/rate-plans/how-rates-work/baseline-allowance.html#accordion-2fb51186db-item-2ea52b55e4
# Baseline Allowances for E-TOU-C Rate Plan

from datetime import datetime, timedelta
import argparse
import os
import pandas as pd
from collections import defaultdict
from datetime import datetime, timedelta
from helpers.main_helpers import get_counties, get_scenario_path, log, to_number, get_timestamp, norcal_counties, socal_counties, central_counties, slugify_county_name
from helpers.electricity_rate_helpers import PGE_RATE_PLANS, SCE_RATE_PLANS, SDGE_RATE_PLANS
from helpers.nem3_export_rates import (
    get_export_rate_table,
    get_export_rate_table_for_county,
    default_options_for_utility,
    NEM3Options,
)
from helpers.utility_helpers import get_utility_for_county


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
def calculate_annual_costs_electricity(load_profile, utility, rate_plan_name):
    annual_costs = defaultdict(float)
    # Now plan_details has a nested structure: season -> {weekdays, weekends}
    plan_details = RATE_PLANS[utility][rate_plan_name]

    for hour_index, hourly_load in enumerate(load_profile):
        season = get_season(hour_index)
        current_datetime = datetime(year=2023, month=1, day=1) + timedelta(hours=hour_index)
        hour = current_datetime.hour

        # Determine whether the current day is a weekday (Monday-Friday) or weekend (Saturday-Sunday)
        dayotw_type = "weekends" if is_weekend(current_datetime) else "weekdays"

        # Retrieve the seasonal rates and then the appropriate day type rates
        season_rates = plan_details.get(season)
        if not season_rates:
            continue

        dayotw_rates = season_rates.get(dayotw_type)
        if not dayotw_rates:
            continue

        if hour in dayotw_rates.get("peakHours", []):
            rate = dayotw_rates.get("peak", 0.0)
        elif "partPeakHours" in dayotw_rates and hour in dayotw_rates.get("partPeakHours", []):
            rate = dayotw_rates["partPeak"]
        elif "superOffPeakHours" in dayotw_rates and hour in dayotw_rates.get("superOffPeakHours", []):
            rate = dayotw_rates["superOffPeak"]
        else:
            rate = dayotw_rates.get("offPeak", 0.0)

        # Calculate the cost for the hour
        energy_cost = hourly_load * rate
        annual_costs[rate_plan_name] += energy_cost

        # Include fixed charges if available (daily charge spread across 24 hours)
        fixed_charge = dayotw_rates.get("fixedCharge", 0.0)
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


def _estimate_monthly_fixed_from_plan(plan_details, year: int, month: int) -> float:
    """Best-effort: infer a monthly fixed from plan details if present (daily basic charge)."""
    # Try weekdays summer first, else any season
    season = 'summer' if 6 <= month <= 9 else 'winter'
    rates = plan_details.get(season, {})
    day_rates = rates.get('weekdays', rates.get('weekends', rates))
    per_day = float(day_rates.get('fixedCharge', 0.0))
    # Days in month
    days = 30
    if month in (1,3,5,7,8,10,12):
        days = 31
    elif month == 2:
        # ignore leap for simplicity
        days = 28
    return per_day * days


def calculate_nem3_annual_costs(
    timestamps,
    import_kwh,
    export_kwh,
    utility: str,
    rate_plan_name: str,
    *,
    options: NEM3Options | None = None,
    export_table: dict | None = None,
):
    """Compute NEM 3.0 bill: monthly energy charges (retail), monthly export credits (ACC), NBCs, fixed/minimum, carry-forward.

    Returns dict keyed by rate plan name with a single annual total in dollars.
    """
    annual_costs = {}
    plan_details = RATE_PLANS[utility][rate_plan_name]
    opts = options or default_options_for_utility(utility)
    export_table = export_table or get_export_rate_table(utility)

    # Ensure aligned series
    ts = pd.to_datetime(timestamps)
    imp = pd.Series(import_kwh).astype(float).reset_index(drop=True)
    exp = pd.Series(export_kwh).astype(float).reset_index(drop=True)
    if len(ts) != len(imp):
        # Fall back to synthetic timestamps if needed
        ts = pd.date_range(start=f"{datetime.now().year}-01-01", periods=len(imp), freq='H')
    if len(exp) != len(imp):
        exp = exp.reindex(range(len(imp))).fillna(0.0)

    # Monthly accounting
    annual_total = 0.0
    carry_credit = 0.0  # dollars
    grouped = pd.DataFrame({'ts': ts, 'imp': imp, 'exp': exp})
    grouped['month'] = grouped['ts'].dt.month
    grouped['hour'] = grouped['ts'].dt.hour

    for month, g in grouped.groupby('month', sort=True):
        # Hourly import energy rates and ACC export credits
        energy_charge = 0.0
        nbc_charge = 0.0
        export_credit = 0.0
        for _, row in g.iterrows():
            dt = pd.Timestamp(row['ts']).to_pydatetime()
            irate = _hourly_import_rate(plan_details, dt)
            acc_rate = float(export_table.get(int(month), [0.0] * 24)[int(row['hour'])])
            kwh_imp = float(row['imp'])
            kwh_exp = float(row['exp'])
            energy_charge += kwh_imp * max(0.0, irate - opts.nbc_dollars_per_kwh)
            nbc_charge += kwh_imp * max(0.0, opts.nbc_dollars_per_kwh)
            export_credit += kwh_exp * acc_rate

        # Apply credits only to energy charge; carry forward remainder
        energy_net = max(0.0, energy_charge - carry_credit - export_credit)
        leftover_credit = max(0.0, (carry_credit + export_credit) - energy_charge)

        # Fixed and minimum charges (prefer explicit options; otherwise infer per plan)
        fixed = opts.fixed_charge_monthly or _estimate_monthly_fixed_from_plan(plan_details, ts.dt.year.iloc[0], int(month))
        minimum = opts.minimum_bill_monthly or 0.0
        month_subtotal = energy_net + nbc_charge + fixed
        month_total = max(month_subtotal, minimum)

        annual_total += month_total
        carry_credit = leftover_credit

        # Optional year-end true-up
        if int(month) == int(opts.true_up_month) and opts.nsc_dollars_per_kwh > 0.0:
            # If modeling NSC in $/kWh, we would need a conversion; treat credit as $ and for simplicity assume no NSC payout here.
            carry_credit = 0.0

    annual_costs[rate_plan_name] = annual_total
    return annual_costs
    
def process_county_scenario_from_series(file_path, county, utility, selected_rate_plan, column_name):
    """Read a specific aggregator column and compute retail annual cost for the given plan."""
    file = os.path.join(file_path, county, f"{INPUT_FILE_NAME}_{county}.csv")
    if not os.path.exists(file):
        raise FileNotFoundError(f"File not found: {file}")
    df = pd.read_csv(file, usecols=[column_name])
    load_profile = df[column_name].astype(float).tolist()
    return calculate_annual_costs_electricity(load_profile, utility, selected_rate_plan)


def process_county_scenario_nem3(file_path, county, utility, selected_rate_plan):
    """Compute NEM3 bill using Aggregator columns: nem3.imports.kwh and nem3.exports.kwh."""
    file = os.path.join(file_path, county, f"{INPUT_FILE_NAME}_{county}.csv")
    if not os.path.exists(file):
        raise FileNotFoundError(f"File not found: {file}")

    df = pd.read_csv(file)
    ts = pd.to_datetime(df['timestamp']) if 'timestamp' in df.columns else pd.date_range('2018-01-01', periods=len(df), freq='H')

    imports_col = "nem3.imports.kwh"
    exports_col = "nem3.exports.kwh"

    opts = default_options_for_utility(utility)
    base_dir = os.path.join("data", "NEM3")
    export_table = get_export_rate_table_for_county(base_dir=base_dir, utility=utility, county_name_or_slug=county)

    annual_solar_nem3 = calculate_nem3_annual_costs(
        ts,
        df[imports_col].astype(float).tolist(),
        df[exports_col].astype(float).tolist(),
        utility,
        selected_rate_plan,
        options=opts,
        export_table=export_table,
    )

    return annual_solar_nem3

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
    
def process(base_input_dir, base_output_dir, scenario, housing_type, counties, use_nem3: bool = False):
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

            # NEM3 overlay for solarstorage (exports credited at ACC, NBCs applied)
            solar_nem3 = process_county_scenario_nem3(scenario_path, county, utility, rate_plan)

            annual_costs_results = build_results_df_with_variants(
                scenario,
                utility,
                retail_default=retail_default,
                retail_solar=retail_solar,
                nem3_solar=solar_nem3,
            )

            results_df = update_df_with_results(results_df, annual_costs_results)

            log_kwargs.update({
                f"annual_electricity_costs_{rate_plan}": to_number(retail_default.get(rate_plan, 0.0)),
                f"annual_electricity_costs_solarstorage_{rate_plan}": to_number(retail_solar.get(rate_plan, 0.0)),
                f"annual_electricity_costs_solarstorage_{rate_plan}_NEM3": to_number(solar_nem3.get(rate_plan, 0.0)),
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
