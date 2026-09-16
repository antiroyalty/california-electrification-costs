"""Matched gas/ICE and electric/EV household costs, with and without solar."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd

from figure_builder.datasets import EAC_COMPONENT_COLUMNS, expected_claim_counties
from figure_builder import git_short_sha
from figure_builder.dispatch import HOUSING_TYPE, LOAD_COL, county_dispatch_input_paths
from figure_builder.metadata import file_identity
from helpers.plot_scenario_comparison_helper import (
    _latest_electricity_csv,
    _latest_gas_csv,
    collect_eac_components_by_county,
)
from tariffs import resolve_county_service_assignment
from tariffs.import_rates import required_nbt_import_plan

HOUSEHOLDS = {
    "gas": "baseline_ice_car_coopt",
    "electric": "full_electric_ev_coopt",
}
CASES = {
    f"{household}_{solar}": (scenario, solar == "optimized")
    for household, scenario in HOUSEHOLDS.items()
    for solar in ("no_solar", "optimized")
}
RETAIL_PLANS = {"PG&E": "E-TOU-D", "SCE": "TOU-D-4-9PM", "SDG&E": "TOU-DR1"}
NON_SOLAR_COSTS = ["capex_electric", "capex_gas", "annual_bill_gas", "vehicle_om"]
DESIGN_COLUMNS = ["solar_kw", "battery_kwh", "solver_cost_gap_usd_per_year",
                  "reporting_cost_difference_usd_per_year"]
MATCHED_SETTINGS = [
    "Utility", "Import Tariff Plan", "Import Tariff Snapshot As Of",
    "Import Tariff Effective Date", "Import Tariff Source ID",
    "NBT Billing Year", "NBT Interconnection Vintage",
    "Battery Capacity Upper Bound (kWh)", "Allow Grid Charging", "Allow Battery Export",
    "Solver Cost Tolerance (USD/year)",
]


def electricity_column(utility: str, with_solar: bool) -> str:
    plan = required_nbt_import_plan(utility) if with_solar else RETAIL_PLANS[utility]
    return f"electricity.{utility}.{plan}" + ("_NEM3" if with_solar else "")


def validate_electrification_costs(frame: pd.DataFrame, counties: set[str]) -> pd.DataFrame:
    """Require four matched cells per county; derive totals from their components."""
    identity = ["case", "scenario", "county_slug", "utility", "electricity_column"]
    required = identity + EAC_COMPONENT_COLUMNS + DESIGN_COLUMNS
    missing = set(required) - set(frame.columns)
    if missing:
        raise ValueError(f"Electrification costs missing columns: {sorted(missing)}")
    result = frame.copy()
    if not counties or result[identity].isna().any().any():
        raise ValueError("Electrification costs require county and case identities")
    expected = {(county, case) for county in counties for case in CASES}
    actual = set(zip(result["county_slug"], result["case"]))
    if actual != expected or result.duplicated(["county_slug", "case"]).any():
        raise ValueError("Electrification costs require exactly four unique cases per county")
    numbers = EAC_COMPONENT_COLUMNS + DESIGN_COLUMNS
    result[numbers] = result[numbers].apply(pd.to_numeric, errors="raise")
    if not np.isfinite(result[numbers].to_numpy()).all():
        raise ValueError("Electrification costs and design values must be finite")
    nonnegative = ["capex_pv", "capex_storage", "solar_kw", "battery_kwh",
                   "solver_cost_gap_usd_per_year"]
    if (result[nonnegative] < 0).any().any():
        raise ValueError("Solar/storage costs, capacities, and solver gaps cannot be negative")
    for case, (scenario, with_solar) in CASES.items():
        selected = result[result["case"] == case]
        if not (selected["scenario"] == scenario).all():
            raise ValueError(f"{case} requires scenario {scenario}")
        for row in selected.to_dict("records"):
            utility = resolve_county_service_assignment(row["county_slug"]).utility.value
            expected_column = electricity_column(utility, with_solar)
            if row["utility"] != utility or row["electricity_column"] != expected_column:
                raise ValueError(
                    f"Unmatched utility or electricity plan for {case}/{row['county_slug']}"
                )
        zero_columns = ["capex_pv", "capex_storage", *DESIGN_COLUMNS]
        if not with_solar and (selected[zero_columns] != 0).any().any():
            raise ValueError("No-solar cases must have zero solar/storage costs, sizes, and gaps")
    for household in HOUSEHOLDS:
        no_solar = result[result["case"] == f"{household}_no_solar"].set_index("county_slug")
        optimized = result[result["case"] == f"{household}_optimized"].set_index("county_slug")
        if not np.allclose(no_solar.loc[sorted(counties), NON_SOLAR_COSTS],
                           optimized.loc[sorted(counties), NON_SOLAR_COSTS], rtol=0, atol=1e-8):
            raise ValueError(f"Non-solar household costs changed with solar adoption: {household}")
    # Negative appliance net costs and vehicle adjustments are valid model inputs.
    totals = result[EAC_COMPONENT_COLUMNS].sum(axis=1)
    if not np.isfinite(totals).all():
        raise ValueError("Annual household totals must be finite")
    if "total_eac" in result:
        recorded = pd.to_numeric(result["total_eac"], errors="raise")
        if not np.allclose(recorded, totals, rtol=0, atol=1e-8):
            raise ValueError("Recorded household totals do not reconcile to their components")
    result["total_eac"] = totals
    return result.sort_values(["county_slug", "case"]).reset_index(drop=True)


def summarize_electrification_costs(frame: pd.DataFrame) -> pd.DataFrame:
    """Positive dollar differences mean savings; positive interaction means a package effect."""
    costs = validate_electrification_costs(frame, set(frame["county_slug"]))
    wide = costs.pivot(index="county_slug", columns="case", values="total_eac")
    wide["electrification_savings_no_solar_usd_per_year"] = (
        wide.gas_no_solar - wide.electric_no_solar
    )
    wide["electrification_savings_optimized_usd_per_year"] = (
        wide.gas_optimized - wide.electric_optimized
    )
    wide["gas_adoption_savings_usd_per_year"] = wide.gas_no_solar - wide.gas_optimized
    wide["electric_adoption_savings_usd_per_year"] = (
        wide.electric_no_solar - wide.electric_optimized
    )
    wide["package_effect_usd_per_year"] = (
        wide.electric_adoption_savings_usd_per_year - wide.gas_adoption_savings_usd_per_year
    )
    optimized = costs[costs["case"].str.endswith("_optimized")].copy()
    # Each saved Coopt Total Cost is rounded to four decimal places. The bound
    # also covers capacity rounding and both certified solver cost gaps.
    optimized["uncertainty"] = (optimized.solver_cost_gap_usd_per_year
                                + optimized.reporting_cost_difference_usd_per_year.abs()
                                + 0.00005)
    wide["comparison_numerical_bound_usd_per_year"] = (
        optimized.groupby("county_slug").uncertainty.sum()
    )
    wide.columns.name = None
    return wide.reset_index()


def _one_row(frame: pd.DataFrame, key: str, value: str, context: str) -> pd.Series:
    selected = frame[frame[key] == value]
    if len(selected) != 1:
        raise ValueError(f"{context} requires one {key}={value}; found {len(selected)}")
    return selected.iloc[0]


def _validate_run_identity(model_run_sha, run_timestamps):
    if not isinstance(model_run_sha, str) or not re.fullmatch(r"[0-9a-f]{7,40}", model_run_sha):
        raise ValueError("model_run_sha must be a 7-40 character lowercase Git SHA")
    if not isinstance(run_timestamps, dict) or set(run_timestamps) != set(HOUSEHOLDS.values()):
        raise ValueError("Identify exactly both optimized scenarios with YYYYMMDD_HH timestamps")
    if any(
        not isinstance(ts, str) or not re.fullmatch(r"\d{8}_\d{2}", ts)
        for ts in run_timestamps.values()
    ):
        raise ValueError("Identify exactly both optimized scenarios with YYYYMMDD_HH timestamps")


def build_electrification_source(
    *, model_run_sha: str, run_timestamps: dict[str, str],
    base_input_dir: str | Path, completion_dir: str | Path, source: str | Path,
    counties: set[str] | None = None,
) -> Path:
    """Collect two completed optimized runs and their original-load counterfactuals.

    Completion labels identify the declared model run. File hashes identify the
    exact collected inputs; they do not reconstruct those files' generation history.
    """
    _validate_run_identity(model_run_sha, run_timestamps)
    counties = expected_claim_counties() if counties is None else set(counties)
    if not counties:
        raise ValueError("At least one county is required")
    base = Path(base_input_dir)
    files = {}

    def record(path):
        identity = file_identity(path)
        files[str(Path(path).resolve())] = identity
        return identity

    frames, settings, weather = [], {}, {}
    for household, scenario in HOUSEHOLDS.items():
        suffix = f"{scenario}_{HOUSING_TYPE.replace('-', '_')}.csv"
        record(base / "capital_costs" / f"capital_costs_{suffix}")
        record(base / "capital_costs" / f"capital_costs_summary_with_pv_{suffix}")
        assets_path = base / scenario / HOUSING_TYPE / "CAPITAL_COSTS" / "electrified_assets.csv"
        record(assets_path)
        assets = pd.read_csv(assets_path)
        bills, designs = {}, {}
        for county in sorted(counties):
            record(Path(completion_dir) / scenario / f"{county}_diagnostics_g{model_run_sha}.html")
            weather_path, load_path = county_dispatch_input_paths(county, scenario, base)
            weather[household, county] = record(weather_path)["sha256"]
            record(load_path)
            load = pd.read_csv(load_path)
            if len(load) != 8760 or LOAD_COL not in load:
                raise ValueError(f"{scenario}/{county} requires a full 8760-hour load profile")
            demand = pd.to_numeric(load[LOAD_COL], errors="raise")
            if not np.isfinite(demand).all() or (demand < 0).any():
                raise ValueError(f"Invalid household electricity demand: {scenario}/{county}")
            design = _one_row(assets, "County", county, "Optimized capacity summary")
            if design[MATCHED_SETTINGS].isna().any():
                raise ValueError(f"Missing optimization settings: {scenario}/{county}")
            settings[household, county] = design[MATCHED_SETTINGS].to_dict()
            designs[county] = design
            locators = (("electricity", _latest_electricity_csv), ("gas", _latest_gas_csv))
            for fuel, locate in locators:
                path = locate(str(base), scenario, HOUSING_TYPE, county, run_timestamps[scenario])
                record(path)
                bills[county, fuel] = pd.read_csv(path)
        for solar, with_solar in (("no_solar", False), ("optimized", True)):
            preferences = [electricity_column(utility, with_solar) for utility in RETAIL_PLANS]
            # Validate the exact columns before the shared collector: its legacy
            # selector also accepts an unmatched but unique numeric candidate.
            selected_bills = {}
            for county in sorted(counties):
                utility = resolve_county_service_assignment(county).utility.value
                column = electricity_column(utility, with_solar)
                row_name = scenario + (".solarstorage" if with_solar else "")
                electric = _one_row(
                    bills[county, "electricity"], "scenario", row_name, "Electricity bill"
                )
                gas = _one_row(bills[county, "gas"], "scenario", row_name, "Gas bill")
                gas_columns = [c for c in gas.index if c.startswith("gas.")]
                if column not in electric or len(gas_columns) != 1:
                    raise ValueError(
                        f"Exact bill plan is missing or ambiguous: {scenario}/{county}/{solar}"
                    )
                selected_bills[county] = (float(electric[column]), float(gas[gas_columns[0]]))
            costs = collect_eac_components_by_county(
                str(base), HOUSING_TYPE, [scenario], sorted(counties),
                timestamp=run_timestamps[scenario], electricity_plan_preference=preferences,
                electricity_variant="nem3" if with_solar else "retail", with_solar=with_solar,
            )
            for row in costs.to_dict("records"):
                county = row["county_slug"]
                design = designs[county]
                utility = resolve_county_service_assignment(county).utility.value
                if not np.allclose([row["annual_bill_electric"], row["annual_bill_gas"]],
                                   selected_bills[county], rtol=0, atol=1e-8):
                    raise ValueError(
                        f"Collector did not use the specified bills: {scenario}/{county}"
                    )
                if (design["Utility"] != utility
                        or design["Import Tariff Plan"] != required_nbt_import_plan(utility)):
                    raise ValueError(
                        f"Optimizer used a different utility or plan: {scenario}/{county}"
                    )
                gap = float(design["Solver Cost Gap (USD/year)"])
                if not 0 <= gap <= float(design["Solver Cost Tolerance (USD/year)"]) + 1e-6:
                    raise ValueError(f"Invalid solver cost gap: {scenario}/{county}")
                row.update(
                    case=f"{household}_{solar}", utility=utility,
                    electricity_column=electricity_column(utility, with_solar),
                    solar_kw=float(design["Solar Capacity (kW)"]) if with_solar else 0.0,
                    battery_kwh=float(design["Battery Capacity (kWh)"]) if with_solar else 0.0,
                    solver_cost_gap_usd_per_year=gap if with_solar else 0.0,
                    reporting_cost_difference_usd_per_year=(
                        row["capex_pv"] + row["capex_storage"] + row["annual_bill_electric"]
                        - float(design["Coopt Total Cost"])
                    ) if with_solar else 0.0,
                )
                frames.append(row)
    for county in counties:
        if settings["gas", county] != settings["electric", county]:
            raise ValueError(f"Optimization settings differ between households: {county}")
        if weather["gas", county] != weather["electric", county]:
            raise ValueError(f"Weather inputs differ between households: {county}")
    costs = validate_electrification_costs(pd.DataFrame(frames), counties)
    summary = summarize_electrification_costs(costs)
    destination = Path(source)
    summary_path = destination.with_suffix(".comparisons.csv")
    for output in (destination, summary_path, destination.with_suffix(".manifest.json")):
        if str(output.resolve()) in files:
            raise ValueError("Comparison outputs cannot replace a source input")
    for path, identity in files.items():
        if file_identity(path)["sha256"] != identity["sha256"]:
            raise ValueError(f"Source input changed during collection: {path}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    costs.to_csv(destination, index=False)
    summary.to_csv(summary_path, index=False)
    manifest = {
        "schema_version": 1, "model_git_sha": model_run_sha,
        "scenario_run_timestamps": run_timestamps, "expected_counties": sorted(counties),
        "households": HOUSEHOLDS, "housing_type": HOUSING_TYPE,
        "discount_rate": 0.07, "incentive_scenario": "full_incentives",
        "matched_settings_by_county": {c: settings["gas", c] for c in sorted(counties)},
        "tariff_comparison": (
            "Match plans between households within each solar choice; "
            "adoption includes the retail-to-NBT plan change."
        ),
        "source_files": list(files.values()), "reporting_code": file_identity(__file__),
        "reporting_git_sha": git_short_sha(),
        "costs": file_identity(destination), "comparisons": file_identity(summary_path),
    }
    destination.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return destination


def load_electrification_costs(source: str | Path) -> pd.DataFrame:
    """Check the saved table against its receipt, then revalidate all four cells."""
    path = Path(source)
    manifest = json.loads(path.with_suffix(".manifest.json").read_text())
    if manifest["schema_version"] != 1 or manifest["households"] != HOUSEHOLDS:
        raise ValueError("Unsupported electrification source manifest")
    _validate_run_identity(manifest["model_git_sha"], manifest["scenario_run_timestamps"])
    if file_identity(path)["sha256"] != manifest["costs"]["sha256"]:
        raise ValueError("Electrification source fingerprint does not match its manifest")
    return validate_electrification_costs(pd.read_csv(path), set(manifest["expected_counties"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-run-sha", required=True)
    parser.add_argument("--gas-run-timestamp", required=True)
    parser.add_argument("--electric-run-timestamp", required=True)
    parser.add_argument("--base-input-dir", required=True)
    parser.add_argument("--completion-dir", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--counties", nargs="+")
    args = parser.parse_args()
    result = build_electrification_source(
        model_run_sha=args.model_run_sha,
        run_timestamps={HOUSEHOLDS["gas"]: args.gas_run_timestamp,
                        HOUSEHOLDS["electric"]: args.electric_run_timestamp},
        base_input_dir=args.base_input_dir, completion_dir=args.completion_dir,
        source=args.source, counties=set(args.counties) if args.counties else None,
    )
    print(f"Wrote four-case costs, comparisons, and source receipt: {result}")


if __name__ == "__main__":
    main()
