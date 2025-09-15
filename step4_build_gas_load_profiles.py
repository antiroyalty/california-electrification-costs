import os
import pandas as pd

from main_helpers import get_scenario_path, get_counties, log, to_number

# ResStock EULP timestamps are in fixed EST (UTC-5, no DST).
TZ_SOURCE_FIXED_EST = 'Etc/GMT+5'            # POSIX sign: +5 == UTC-5
TZ_TARGET_LOCAL = 'America/Los_Angeles'      # or 'US/Pacific'

# Conversion factor
KWH_TO_THERMS = 0.0341296

# Define natural gas end use columns
END_USE_COLUMNS = {
    "heating": ['out.natural_gas.heating.energy_consumption'],
    "hot_water": ['out.natural_gas.hot_water.energy_consumption'],
    "cooking": ['out.natural_gas.range_oven.energy_consumption'],
    "appliances": ['out.natural_gas.clothes_dryer.energy_consumption'],
    "misc": ['out.natural_gas.fireplace.energy_consumption'],
}

OUTPUT_FILE_PREFIX = "gas_loads"

def _localize_to_pt(ts_series: pd.Series) -> pd.Series:
    """Localize naive EST (*fixed* UTC-5) -> convert to Pacific -> drop tz."""
    ts = pd.to_datetime(ts_series)
    return (
        ts.dt.tz_localize(TZ_SOURCE_FIXED_EST)      # fixed EST, no DST
          .dt.tz_convert(TZ_TARGET_LOCAL)           # to PT (handles DST here)
          .dt.tz_localize(None)                     # naive local time
    )

def _resample_right_ending(df: pd.DataFrame, freq="H", how="sum") -> pd.DataFrame:
    """
    Resample from RIGHT-labeled 15-min intervals (ending timestamps) to hourly.
    Use right-labeled/right-closed bins so totals land in the intended clock hour.
    """
    if df.empty:
        return df
    if how == "sum":
        return df.resample(freq, label="right", closed="right").sum()
    elif how == "mean":
        return df.resample(freq, label="right", closed="right").mean()
    else:
        raise ValueError("Unsupported aggregation method: choose 'sum' or 'mean'")

def process_building_data(data: pd.DataFrame, end_uses: list[str]) -> pd.DataFrame:
    """
    - Validates columns
    - Converts timestamp from fixed EST -> Pacific (naive)
    - Sets timestamp index
    - (Optional) resamples 15-min ending -> hourly (sum)
    - Returns a DataFrame with:
        end-use columns (kWh),
        'load.gas.total.kwh'
      indexed by hourly Pacific timestamps (right-labeled)
    """
    required = ['timestamp'] + end_uses
    if not all(col in data.columns for col in required):
        raise ValueError("Missing required columns: 'timestamp' and/or end_uses.")

    # Time conversion (do it ONCE)
    data = data[required].copy()
    data['timestamp'] = _localize_to_pt(data['timestamp'])
    data = data.set_index('timestamp').sort_index()

    # If source is 15-min ending (ResStock), resample to hourly with right/right bins
    # If you prefer to keep 15-min, skip resample and adjust downstream accordingly.
    data = _resample_right_ending(data, freq="H", how="sum")

    # Total across end uses
    data['load.gas.total.kwh'] = data[end_uses].sum(axis=1)

    return data

def update_county_totals(county_gas_totals: pd.DataFrame | None,
                         building_gas_totals: pd.DataFrame,
                         building_count: int,
                         end_uses: list[str]) -> pd.DataFrame:
    """
    Sum building profiles into a county-wide total, aligned on timestamp index.
    Keeps per-end-use totals with '.gas.total.kwh' suffix, plus overall totals.
    """
    # Prepare building columns with suffixed names
    suffixed_map = {col: f"{col}.gas.total.kwh" for col in end_uses}
    b_df = building_gas_totals.rename(columns=suffixed_map)
    keep_cols = list(suffixed_map.values()) + ['load.gas.total.kwh']
    b_df = b_df[keep_cols]

    if county_gas_totals is None:
        county_gas_totals = b_df.copy()
    else:
        # Align on timestamp index and add with fill_value=0 to handle gaps
        county_gas_totals = county_gas_totals.add(b_df, fill_value=0)

    # Derived therms, building count (scalar column)
    county_gas_totals['load.gas.total.therms'] = county_gas_totals['load.gas.total.kwh'] * KWH_TO_THERMS
    county_gas_totals['building_count'] = building_count

    return county_gas_totals


def sum_county_gas_profiles(input_dir: str, end_uses: list[str]) -> tuple[pd.DataFrame | None, int]:
    county_gas_totals = None
    building_count = 0

    if not os.path.exists(input_dir):
        return None, 0

    for fname in os.listdir(input_dir):
        fpath = os.path.join(input_dir, fname)
        if not (fname.endswith('.parquet') and os.path.isfile(fpath)):
            continue

        try:
            raw = pd.read_parquet(fpath)
        except Exception as e:
            log(error=f"Error reading {fpath}: {e}")
            continue

        try:
            b_df = process_building_data(raw, end_uses)
        except Exception as e:
            log(error=f"Error processing {fpath}: {e}")
            continue

        building_count += 1
        county_gas_totals = update_county_totals(county_gas_totals, b_df, building_count, end_uses)

    return county_gas_totals, building_count

def average_county_gas_profiles(county_gas_totals: pd.DataFrame,
                                building_count: int,
                                end_uses: list[str]) -> pd.DataFrame:
    if county_gas_totals is None or building_count <= 0:
        return county_gas_totals

    df = county_gas_totals.copy()

    # Building-average totals
    df['load.gas.building_avg.kwh'] = df['load.gas.total.kwh'] / building_count
    df['load.gas.building_avg.therms'] = df['load.gas.building_avg.kwh'] * KWH_TO_THERMS

    # Per end-use building averages (kWh and therms)
    for col in end_uses:
        total_col = f"{col}.gas.total.kwh"
        avg_kwh_col = f"{col}.gas.building_avg.kwh"
        avg_therms_col = f"{col}.gas.building_avg.therms"
        if total_col in df.columns:
            df[avg_kwh_col] = df[total_col] / building_count
            df[avg_therms_col] = df[avg_kwh_col] * KWH_TO_THERMS

    return df


def save_county_gas_profiles(county_gas_totals: pd.DataFrame, county: str, output_file: str):
    # Annual-ish rollups for logging (sum over time rows)
    log(
        at="step4_build_gas_profiles#save_county_gas_profiles",
        gas_heating_kwh=to_number(county_gas_totals.get('out.natural_gas.heating.energy_consumption.gas.building_avg.kwh', pd.Series(dtype=float)).sum()),
        gas_range_oven_kwh=to_number(county_gas_totals.get('out.natural_gas.range_oven.energy_consumption.gas.building_avg.kwh', pd.Series(dtype=float)).sum()),
        gas_hot_water_kwh=to_number(county_gas_totals.get('out.natural_gas.hot_water.energy_consumption.gas.building_avg.kwh', pd.Series(dtype=float)).sum()),
        annual_gas_load_kwh=to_number(county_gas_totals.get('load.gas.building_avg.kwh', pd.Series(dtype=float)).sum()),
        annual_gas_load_therms=to_number(county_gas_totals.get('load.gas.building_avg.therms', pd.Series(dtype=float)).sum()),
        saved_at=output_file
    )

    out = county_gas_totals.copy()
    out.index.name = "timestamp"
    out.reset_index().to_csv(output_file, index=False)

def build_county_gas_profile(scenario: str, housing_type: str, county: str,
                             county_dir: str, output_file: str, end_uses: list[str]):
    county_gas_totals, building_count = sum_county_gas_profiles(county_dir, end_uses)

    if county_gas_totals is None or building_count == 0:
        log(details=f"No valid data found in {county_dir} for {scenario} - {housing_type}. Skipping.")
        return

    county_gas_totals = average_county_gas_profiles(county_gas_totals, building_count, end_uses)
    save_county_gas_profiles(county_gas_totals, county, output_file)


def should_skip_processing(output_path: str, force_recompute: bool) -> bool:
    if force_recompute:
        return False  # Always regenerate if forced
    return os.path.exists(output_path)


def process(scenario: str,
            scenario_mapping: dict,
            housing_type: str,
            base_input_dir: str,
            base_output_dir: str,
            counties=None,
            force_recompute: bool = True):
    if scenario != "baseline":
        log(at="step4_build_gas_load_profiles", message="no new gas profiles needed to be downloaded")
        return

    scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
    counties = get_counties(scenario_path, counties)

    for county in counties:
        log(
            at="step4_build_gas_load_profiles#process",
            details=f"Processing gas load profile in {county} for {scenario}, {housing_type}",
        )

        county_dir = os.path.join(scenario_path, county, "buildings")
        output_dir = os.path.join(base_output_dir, scenario, housing_type, county)
        os.makedirs(output_dir, exist_ok=True)
        output_file = os.path.join(output_dir, f"{OUTPUT_FILE_PREFIX}_{county}.csv")

        if should_skip_processing(output_file, force_recompute):
            continue

        if not os.path.exists(county_dir):
            log(details=f"County directory not found: {county_dir}")
            continue

        # Collect all GAS end-use columns relevant to the scenario
        end_use_categories = scenario_mapping[scenario]['gas']
        end_uses = [col for category in end_use_categories for col in END_USE_COLUMNS[category]]

        build_county_gas_profile(scenario, housing_type, county, county_dir, output_file, end_uses)

if __name__ == '__main__':
    SCENARIOS = {
        "baseline": {"gas": {"heating", "hot_water", "cooking"}, "electric": {"appliances", "misc"}}
    }

    process(
        scenario="baseline",
        scenario_mapping=SCENARIOS,
        housing_type="single-family-detached",
        base_input_dir="data",
        base_output_dir="data/loadprofiles",
        counties=["Alameda County"],
        force_recompute=True
    )