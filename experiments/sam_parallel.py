"""Run a local SAM comparison without changing the production pipeline.

Use Python 3.11 with NREL-PySAM==7.1.1.post1. Run from the repository root:
python -m experiments.sam_parallel --counties alameda los-angeles
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd
import PySAM.Battery as Battery
import PySAM.BatteryTools as BatteryTools
import PySAM.Pvwattsv8 as Pvwatts
import PySAM.PySSC as PySSC
import PySAM.ResourceTools as ResourceTools

from evaluations.constants import DEFAULT_DISCOUNT_RATE
from evaluations.eac import alpha_batt_npv, crf
from pipeline.steps.step9b_cooptimize_core import CooptInputs, FlowSeries, _solve_lp
from pipeline.steps.step9b_cooptimize_pv_battery import (
    DEFAULT_BATT_CAPEX_PER_KWH,
    DEFAULT_PV_CAPEX_PER_KW,
    _write_step9_outputs,
)
from pipeline.steps.step9_solar_storage_dispatch_core import (
    prepare_weather_and_load,
    pv_timeseries_ac_kwh,
)
from tariffs import (
    EnergyFlows,
    NBTScenario,
    TariffCatalog,
    calculate_nbt_bill,
    resolve_county_service_assignment,
)
from tariffs.calendar import full_year_hourly_index


ROOT = Path(__file__).resolve().parents[1]
LOAD_COLUMN = "electricity.real_and_simulated.for_typical_county_home.kwh"
HOURS = 8760
PV_DESIGN = {
    "system_capacity": 1.0,  # DC nameplate kW; gen is AC kW.
    "tilt": 20.0,
    "azimuth": 180.0,
    "array_type": 1,  # Fixed roof mount.
    "module_type": 0,
    "losses": 14.0,
    "dc_ac_ratio": 1.2,
    "inv_eff": 96.0,
}
FLOW_OUTPUTS = {
    "pv_to_load": "system_to_load",
    "pv_to_batt": "system_to_batt",
    "pv_to_grid": "system_to_grid",
    "batt_to_load": "batt_to_load",
    "batt_to_grid": "batt_to_grid",
    "grid_to_load": "grid_to_load",
    "grid_to_batt": "grid_to_batt",
}


def hourly(values, name, *, nonnegative=True):
    """Require one complete non-leap year of finite hourly interval values."""
    array = np.asarray(values, dtype=float)
    if array.shape != (HOURS,) or not np.isfinite(array).all():
        raise ValueError(f"{name} must contain exactly 8760 finite hourly values")
    if nonnegative and np.any(array < -1e-6):
        raise ValueError(f"{name} contains negative values")
    # Only normalize numerical solver residue, using the production tolerance.
    return np.maximum(array, 0.0) if nonnegative else array


def load_inputs(weather_path, load_path):
    """Validate the explicit UTC NSRDB and local standard-time load contract."""
    with weather_path.open(newline="") as stream:
        reader = csv.reader(stream)
        metadata = dict(zip(next(reader), next(reader)))
    if float(metadata["Time Zone"]) != 0 or float(metadata["Local Time Zone"]) != -8:
        raise ValueError("This experiment requires UTC weather and PST (UTC-8) loads")
    weather = pd.read_csv(weather_path, skiprows=2)
    required = ["Year", "Month", "Day", "Hour", "Minute", "DNI", "DHI", "GHI",
                "Temperature", "Wind Speed"]
    for column in required:
        hourly(weather[column], column, nonnegative=column != "Temperature")
    # TMY source years vary by month. Verify month/day/hour against a non-leap year.
    clock = pd.date_range("2018-01-01", periods=HOURS, freq="h")
    for column, expected in [("Month", clock.month), ("Day", clock.day), ("Hour", clock.hour)]:
        if not np.array_equal(weather[column], expected):
            raise ValueError(f"Weather {column} is not a complete ordered hourly year")
    if not (weather.Minute == 30).all():
        raise ValueError("Expected NSRDB hourly irradiance samples at minute 30")
    load_frame = pd.read_csv(load_path)
    timestamps = pd.DatetimeIndex(pd.to_datetime(load_frame.timestamp, errors="raise"))
    if timestamps.tz is not None or timestamps.has_duplicates:
        raise ValueError("Load timestamps must be unique local standard-time values")
    if not (np.diff(timestamps.asi8) == pd.Timedelta(hours=1).value).all():
        raise ValueError("Load timestamps must have consecutive one-hour intervals")
    start = np.flatnonzero((timestamps.month == 1) & (timestamps.day == 1)
                           & (timestamps.hour == 0) & (timestamps.minute == 0))
    if len(start) != 1:
        raise ValueError("Load must contain exactly one January 1 midnight")
    load = np.roll(hourly(load_frame[LOAD_COLUMN], "load_kwh"), -int(start[0]))
    # These calls reproduce the current research path only after strict validation.
    old_weather, old_load = prepare_weather_and_load(
        str(weather_path), str(load_path), LOAD_COLUMN
    )
    if not np.array_equal(load, old_load):
        raise ValueError("Production and prototype load alignment disagree")
    resource = ResourceTools.SAM_CSV_to_solar_data(str(weather_path))
    return load, old_weather, resource, int(start[0])


def sam_pv_yield(resource):
    """Run SAM in the weather time basis, then shift AC output to PST once."""
    model = Pvwatts.default("PVWattsNone")
    model.SystemDesign.assign(PV_DESIGN)
    model.SolarResource.solar_resource_data = resource
    model.execute()
    # At a one-hour interval, AC average kW equals interval kWh numerically.
    return np.roll(hourly(model.Outputs.gen, "PVWatts gen"), -8)


def legacy_weather_diagnostic(resource):
    """Reproduce the deleted pipeline's irradiance-only shift for attribution."""
    shifted = dict(resource)
    for key in ["dn", "df", "gh", "tdry", "tdew", "rhum", "wdir", "wspd"]:
        if key in shifted:  # Optional NSRDB meteorological fields.
            shifted[key] = np.roll(shifted[key], -8).tolist()
    # This intentionally wrong input is used only for the diagnostic.
    return float(sam_pv_yield(shifted).sum())


def validate_flows(load, pv, flows):
    arrays = {key: hourly(getattr(flows, key), key) for key in FLOW_OUTPUTS}
    load_residual = arrays["pv_to_load"] + arrays["batt_to_load"] + arrays["grid_to_load"] - load
    pv_residual = arrays["pv_to_load"] + arrays["pv_to_batt"] + arrays["pv_to_grid"] - pv
    imports = arrays["grid_to_load"] + arrays["grid_to_batt"]
    exports = arrays["pv_to_grid"] + arrays["batt_to_grid"]
    residual = float(max(np.abs(load_residual).max(), np.abs(pv_residual).max()))
    if residual > 1e-5:
        raise ValueError(f"Hourly AC energy balance failed: {residual} kWh")
    if np.any((imports > 1e-6) & (exports > 1e-6)):
        raise ValueError("Simultaneous meter imports and exports")
    if arrays["grid_to_batt"].max() > 1e-6:
        raise ValueError("Grid charging occurred despite the PV-only charging contract")
    return imports, exports, residual


def simulate_battery(load, pv, battery_kwh_dc, battery_kw_ac, buy, sell,
                     *, custom_dispatch_kw=None, initial_soc_percent=20.0):
    """Simulate a fresh detailed SAM battery; no candidate shares SSC data."""
    load, pv = hourly(load, "load"), hourly(pv, "pv")
    for value in [battery_kwh_dc, battery_kw_ac, initial_soc_percent]:
        if not np.isfinite(value):
            raise ValueError("Battery sizing and SOC must be finite")
    if battery_kwh_dc < 0 or battery_kw_ac < 0:
        raise ValueError("Battery capacity and power cannot be negative")
    if not 20 <= initial_soc_percent <= 90:
        raise ValueError("Initial battery SOC must lie within 20–90 percent")
    if battery_kwh_dc == 0:
        if battery_kw_ac != 0:
            raise ValueError("A zero-capacity battery must have zero power")
        zeros = np.zeros(HOURS).tolist()
        flows = FlowSeries(np.minimum(load, pv).tolist(), zeros,
                           np.maximum(pv-load, 0).tolist(), zeros, zeros,
                           np.maximum(load-pv, 0).tolist(), zeros, zeros)
        return flows, {"actual_battery_kwh_dc": 0.0, "actual_battery_kw_ac": 0.0,
                       "initial_soc_percent": 0.0, "final_soc_percent": 0.0}
    if battery_kw_ac == 0:
        raise ValueError("A positive-capacity battery requires positive power")
    model = Battery.default("CustomGenerationBatteryResidential")
    model.Lifetime.assign({"analysis_period": 1, "system_use_lifetime_output": 0})
    model.Load.load = load.tolist()
    model.SystemOutput.gen = pv.tolist()
    model.BatteryCell.assign({"batt_minimum_SOC": 20, "batt_maximum_SOC": 90,
                             "batt_initial_SOC": initial_soc_percent})
    efficiency = 100 * np.sqrt(0.96)
    model.BatterySystem.assign({"batt_ac_or_dc": 1, "batt_replacement_option": 0,
                               "batt_ac_dc_efficiency": efficiency,
                               "batt_dc_ac_efficiency": efficiency})
    # DC nominal capacity matches the optimizer's SOC state and capex basis.
    # The helper also updates cell counts, current limits, mass, and surface area.
    BatteryTools.battery_model_sizing(
        model, battery_kw_ac / (efficiency / 100), battery_kwh_dc, 50.4,
        size_by_ac_not_dc=False,
    )
    # Apply the exact requested AC power limit on both converter directions.
    system = model.BatterySystem
    voltage = system.batt_computed_series * model.BatteryCell.batt_Vnom_default
    system.assign({"batt_power_charge_max_kwac": battery_kw_ac,
                   "batt_power_discharge_max_kwac": battery_kw_ac,
                   "batt_power_charge_max_kwdc": battery_kw_ac * efficiency / 100,
                   "batt_power_discharge_max_kwdc": battery_kw_ac / (efficiency / 100),
                   "batt_current_charge_max": battery_kw_ac * efficiency / 100 / voltage * 1000,
                   "batt_current_discharge_max": (
                       battery_kw_ac / (efficiency / 100) / voltage * 1000)})
    model.BatteryDispatch.assign({
        "batt_dispatch_choice": 4 if custom_dispatch_kw is None else 2,
        "batt_dispatch_auto_can_gridcharge": 0,
        "batt_dispatch_auto_can_charge": 1,
        "batt_dispatch_auto_btm_can_discharge_to_grid": 1,
        "batt_dispatch_charge_only_system_exceeds_load": 1,
        "batt_dispatch_discharge_only_load_exceeds_system": 0,
        "batt_cycle_cost_choice": 1, "batt_cycle_cost": [0.0],
    })
    if custom_dispatch_kw is not None:
        model.BatteryDispatch.batt_custom_dispatch = hourly(
            custom_dispatch_kw, "custom battery power", nonnegative=False
        ).tolist()
    # Explicit hourly signals avoid SAM's sample retail tariff and calendar defaults.
    # SAM's dispatch bill is an approximation; tariffs.calculate_nbt_bill scores it.
    model.ElectricityRates.assign({
        "ur_en_ts_buy_rate": 1, "ur_en_ts_sell_rate": 1,
        "ur_ts_buy_rate": hourly(buy, "buy rates").tolist(),
        "ur_ts_sell_rate": hourly(sell, "sell rates").tolist(),
        "ur_metering_option": 2, "ur_dc_enable": 0, "ur_sell_eq_buy": 0,
        "ur_monthly_fixed_charge": 0, "ur_monthly_min_charge": 0,
        "ur_annual_min_charge": 0, "rate_escalation": [0.0],
        "ur_ec_sched_weekday": [[1]*24 for _ in range(12)],
        "ur_ec_sched_weekend": [[1]*24 for _ in range(12)],
        "ur_ec_tou_mat": [[1, 1, 1e38, 0, 0, 0]],
    })
    model.execute()
    actual_capacity = float(model.Outputs.batt_bank_installed_capacity)
    soc = hourly(model.Outputs.batt_SOC, "battery SOC percent")
    flows = FlowSeries(**{key: hourly(getattr(model.Outputs, value), value).tolist()
                          for key, value in FLOW_OUTPUTS.items()},
                       soc=(soc * actual_capacity / 100).tolist())
    validate_flows(load, pv, flows)
    return flows, {"actual_battery_kwh_dc": actual_capacity,
                   "actual_battery_kw_ac": float(system.batt_power_discharge_max_kwac),
                   "initial_soc_percent": initial_soc_percent,
                   "final_soc_percent": float(soc[-1]),
                   "final_capacity_percent": float(model.Outputs.batt_capacity_percent[-1])}


def score(load, pv, flows, timestamps, tariff, pv_kw, battery_kwh, pv_cost, battery_cost):
    imports, exports, residual = validate_flows(load, pv, flows)
    annual_pv = pv_kw * pv_cost * crf(DEFAULT_DISCOUNT_RATE, 25)
    annual_battery = battery_kwh * battery_cost * alpha_batt_npv(DEFAULT_DISCOUNT_RATE, 15, 25)
    result = {"pv_kw": float(pv_kw), "battery_kwh_dc": float(battery_kwh),
              "annual_load_kwh": float(load.sum()), "annual_pv_kwh": float(pv.sum()),
              "annual_import_kwh": float(imports.sum()), "annual_export_kwh": float(exports.sum()),
              "annual_pv_capital_usd": float(annual_pv),
              "annual_battery_capital_usd": float(annual_battery),
              "max_ac_balance_residual_kwh": residual}
    try:
        ledger = calculate_nbt_bill(EnergyFlows(timestamps, imports, exports), tariff)
    except KeyError as exc:
        # A known missing external tariff source is a visible unavailable result.
        # Never assign a surrogate bill or rank this candidate as a success.
        if not str(exc.args[0]).startswith("Expected one EEC adjustment rate"):
            raise
        result.update(billing_status="unavailable", billing_error=str(exc),
                      annual_bill_usd=None, annual_electricity_and_der_capital_usd=None)
    else:
        result.update(billing_status="ready", annual_bill_usd=ledger.annual_amount_due,
                      annual_electricity_and_der_capital_usd=(
                          ledger.annual_amount_due + annual_pv + annual_battery))
    return result


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def audit_native_size(inputs, winner, pv_cost, battery_cost):
    """Hold SAM's chosen capacities fixed and re-optimize ideal battery dispatch."""
    return _solve_lp(inputs, fixed_pv_kw=winner["pv_kw"],
                     fixed_batt_kwh=winner["battery_kwh_dc"],
                     c_pv_kw=pv_cost, c_batt_kwh=battery_cost)


def run_county(args, county, output):
    inputs_path = args.input_root / args.scenario / args.housing_type / county
    weather_path = inputs_path / f"weather_TMY_{county}.csv"
    load_path = inputs_path / f"combined_profiles_{args.scenario}_{county}.csv"
    load, old_weather, resource, load_shift = load_inputs(weather_path, load_path)
    nbt = NBTScenario()
    tariff = TariffCatalog().bundle(resolve_county_service_assignment(county).utility, nbt)
    timestamps = full_year_hourly_index(nbt.billing_year)
    buy = tariff.import_schedule.rates_for(timestamps)
    sell = [v + tariff.acc_plus_rate for v in tariff.export_schedule.rates_for(timestamps)]
    sam_yield = sam_pv_yield(resource)
    old_yield = hourly(pv_timeseries_ac_kwh(old_weather, 1.0), "research PV yield")
    county_output = output / county
    county_output.mkdir()
    write_json(county_output / "inputs.json", {
        "weather_sha256": hashlib.sha256(weather_path.read_bytes()).hexdigest(),
        "load_sha256": hashlib.sha256(load_path.read_bytes()).hexdigest(),
        "weather_file": str(weather_path), "load_file": str(load_path),
        "load_roll_left_hours": load_shift, "weather_timezone": resource["tz"],
        "local_timezone": -8, "tariff": asdict(nbt), "utility": tariff.utility.value,
        "import_plan": tariff.import_schedule.plan_name,
        "research_yield_kwh_per_kw": float(old_yield.sum()),
        "sam_yield_kwh_per_kwdc": float(sam_yield.sum()),
        "legacy_misaligned_sam_yield_kwh_per_kwdc": legacy_weather_diagnostic(resource),
    })
    pd.DataFrame({"timestamp": timestamps, "load_kwh": load, "research_pv_per_kw": old_yield,
                  "sam_pv_per_kwdc": sam_yield, "buy_usd_per_kwh": buy,
                  "sell_usd_per_kwh": sell}).to_csv(
                      county_output / "inputs_hourly.csv", index=False)
    results = []

    def record(label, yield_per_kw, pv_kw, capacity, flows, extra):
        row = score(load, yield_per_kw * pv_kw, flows, timestamps, tariff,
                    pv_kw, capacity, args.pv_cost, args.battery_cost)
        row.update(case=label, county=county, **extra)
        case_output = county_output / label
        case_output.mkdir()
        _write_step9_outputs(str(case_output), county, list(timestamps), load.tolist(),
                             yield_per_kw.tolist(), pv_kw, flows)
        write_json(case_output / "metrics.json", row)
        results.append(row)
        return row

    for label, yield_per_kw in [("research_milp", old_yield), ("sam_pv_milp", sam_yield)]:
        print(f"{county}: solving {label}", flush=True)
        solved = _solve_lp(CooptInputs(load.tolist(), yield_per_kw.tolist(), buy, sell),
                           c_pv_kw=args.pv_cost, c_batt_kwh=args.battery_cost)
        record(label, yield_per_kw, solved.pv_kw, solved.batt_kwh, solved.flows,
               {"marginal_objective_usd": solved.total_cost, "battery_kw_ac": solved.batt_kw})
    # Replay the optimized AC schedule through SAM's detailed physical battery.
    f = solved.flows
    schedule = np.array(f.batt_to_load) + f.batt_to_grid - np.array(f.pv_to_batt) - f.grid_to_batt
    initial_soc = 100 * f.soc[0] / solved.batt_kwh if solved.batt_kwh else 20.0
    replay, details = simulate_battery(load, sam_yield * solved.pv_kw, solved.batt_kwh,
                                      solved.batt_kw, buy, sell,
                                      custom_dispatch_kw=schedule, initial_soc_percent=initial_soc)
    actual_power = np.array(replay.batt_to_load) + replay.batt_to_grid - np.array(replay.pv_to_batt)
    details["dispatch_absolute_error_kwh"] = float(np.abs(actual_power - schedule).sum())
    record("sam_battery_replay", sam_yield, solved.pv_kw,
           details["actual_battery_kwh_dc"], replay, details)

    # Explicit finite joint size search using SAM RetailRateDispatch (mode 4).
    # Include the continuous optimizer's sizes as an additional paired candidate.
    match_kw = float(load.sum() / sam_yield.sum())
    pairs = {(fraction * match_kw, capacity) for fraction in args.pv_load_fractions
             for capacity in args.battery_sizes}
    pairs.add((solved.pv_kw, solved.batt_kwh))
    candidates = []
    for i, (pv_kw, capacity) in enumerate(sorted(pairs)):
        print(f"{county}: SAM size candidate {i+1}/{len(pairs)}", flush=True)
        flows, details = simulate_battery(load, sam_yield * pv_kw, capacity, capacity,
                                          buy, sell)
        row = record(f"sam_native_{i:03d}", sam_yield, pv_kw,
                     details["actual_battery_kwh_dc"], flows, details)
        candidates.append(row)
    ready = [row for row in candidates if row["billing_status"] == "ready"]
    if not ready:
        raise ValueError("No SAM candidate has a supported realized tariff bill")
    winner = min(ready, key=lambda row: row["annual_electricity_and_der_capital_usd"])
    write_json(county_output / "native_search.json", {
        "best_evaluable_case": winner["case"], "candidate_count": len(candidates),
        "unavailable_bill_count": len(candidates) - len(ready),
        "global_optimality_claim": False, "power_constraint": "1 kW AC per requested kWh DC",
        "ranking": "First-year realized NBT bill plus annualized capital; no terminal SOC credit",
    })
    if winner["battery_kwh_dc"] > 0:
        print(f"{county}: auditing the realized bill at SAM's chosen sizes", flush=True)
        checked = audit_native_size(
            CooptInputs(load.tolist(), sam_yield.tolist(), buy, sell), winner,
            args.pv_cost, args.battery_cost,
        )
        record("sam_pv_milp_at_native_size", sam_yield, checked.pv_kw, checked.batt_kwh,
               checked.flows, {"marginal_objective_usd": checked.total_cost,
                               "battery_kw_ac": checked.batt_kw})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=ROOT / "data/loadprofiles")
    parser.add_argument("--output", type=Path, default=ROOT / "analysis_results/sam_parallel")
    parser.add_argument("--scenario", default="baseline_coopt")
    parser.add_argument("--housing-type", default="single-family-detached")
    parser.add_argument("--counties", nargs="+", default=["alameda", "los-angeles"])
    parser.add_argument("--pv-cost", type=float, default=DEFAULT_PV_CAPEX_PER_KW)
    parser.add_argument("--battery-cost", type=float, default=DEFAULT_BATT_CAPEX_PER_KWH)
    parser.add_argument("--pv-load-fractions", nargs="+", type=float, default=[0, .5, 1, 1.5])
    parser.add_argument("--battery-sizes", nargs="+", type=float, default=[0, 5, 10, 20, 40])
    parser.add_argument("--expected-pysam", choices=["6.0.1", "7.1.1.post1"],
                        default="7.1.1.post1")
    args = parser.parse_args()
    version = importlib.metadata.version("NREL-PySAM")
    if version != args.expected_pysam:
        raise RuntimeError(f"Expected NREL-PySAM=={args.expected_pysam}; found {version}")
    for values, maximum, name in [(args.pv_load_fractions, 1.5, "PV/load fractions"),
                                   (args.battery_sizes, 40, "battery sizes")]:
        if any(not np.isfinite(v) or not 0 <= v <= maximum for v in values):
            raise ValueError(f"{name} must be finite and between 0 and {maximum}")
    if any(not np.isfinite(v) or v <= 0 for v in [args.pv_cost, args.battery_cost]):
        raise ValueError("Capital costs must be positive finite values")
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = {"python": sys.version, "pysam": version, "ssc": PySSC.PySSC().version(),
                "head": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "pv_design": PV_DESIGN, "arguments": {k: str(v) if isinstance(v, Path) else v
                                                       for k, v in vars(args).items()},
                "discount_rate": DEFAULT_DISCOUNT_RATE, "status": "running"}
    manifest["code_and_tariff_sha256"] = {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for pattern in ["experiments/sam_parallel.py", "pipeline/steps/step9*py",
                        "tariffs/*.py", "data/tariffs/*.csv", "data/tariffs/*.json",
                        "evaluations/*.py", "appliances/*.py"] for path in ROOT.glob(pattern)
    }
    write_json(args.output / "manifest.json", manifest)
    rows = []
    for county in args.counties:
        rows.extend(run_county(args, county, args.output))
        pd.DataFrame(rows).to_csv(args.output / "comparison.csv", index=False)
    manifest["status"] = "complete"
    write_json(args.output / "manifest.json", manifest)
    print(f"Results: {args.output / 'comparison.csv'}")


if __name__ == "__main__":
    main()
