"""Explicit county credit runs preserve their accounting through saved artifacts."""

from dataclasses import asdict
import json
import sys
from unittest.mock import patch

import pandas as pd
import pytest

from appliances.battery_storage import BatteryStorageAppliance
from appliances.solar_system import SolarSystemAppliance
from evaluations.eac import compute_eac_from_inputs
from evaluations.federal_credits import (
    FederalCreditCase, FederalCreditReceipts, HouseholdFederalCredits, PVStorageCreditPolicy,
)
from pipeline.config import Config
from pipeline.solver import SolverOptions
from pipeline.steps import step9b_cooptimize_pv_battery as step
from pipeline.steps.step9b_cooptimize_core import CooptInputs, _solve_lp
from tariffs import NBTAnnualTerms, NBTScenario, TariffCatalog


POLICY = PVStorageCreditPolicy(FederalCreditCase.PV_STORAGE, 1, .5)
SCENARIO = "full_electric_ev_coopt"
HOUSING = "single-family-detached"


@pytest.mark.parametrize("case", list(FederalCreditCase))
def test_config_passes_policy_and_gross_prices_without_legacy_incentives(tmp_path, case):
    from pipeline.modules import solar_storage as module

    policy = PVStorageCreditPolicy(case, 1, .5)
    cfg = Config(SCENARIO, HOUSING, ["Alameda County"], base_input_dir=str(tmp_path),
                 coopt_federal_credit_policy=policy)
    # Distinct net prices prevent today's equal gross/net defaults hiding a wiring bug.
    with patch.object(module, "WeatherFiles"), patch.object(module, "Step9bCoopt") as coopt, \
         patch.object(SolarSystemAppliance, "per_kw_cost_net", return_value=1) as net_pv, \
         patch.object(BatteryStorageAppliance, "per_kwh_cost_net", return_value=2) as net_battery:
        module.run(cfg)
    kwargs = coopt.process.call_args.kwargs
    assert kwargs["federal_credit_policy"] == policy
    assert kwargs["pv_capex_per_kw"] == SolarSystemAppliance.per_kw_cost()
    assert kwargs["batt_capex_per_kwh"] == BatteryStorageAppliance.per_kwh_cost()
    net_pv.assert_not_called()
    net_battery.assert_not_called()


def test_fixed_dispatch_cannot_silently_ignore_the_policy(tmp_path):
    from pipeline.modules import solar_storage as module

    cfg = Config("baseline", HOUSING, base_input_dir=str(tmp_path),
                 coopt_federal_credit_policy=POLICY)
    with patch.object(module, "WeatherFiles") as weather:
        with pytest.raises(ValueError, match="requires a _coopt scenario"):
            module.run(cfg)
    weather.process.assert_not_called()


def test_legacy_reports_reject_federal_sizing_without_household_receipts(tmp_path):
    from pipeline.modules import visualization as module

    cfg = Config(SCENARIO, HOUSING, output_dir=str(tmp_path / "reports"),
                 coopt_federal_credit_policy=POLICY)
    with patch.object(module, "PaybackPeriods") as payback:
        with pytest.raises(ValueError, match="explicit federal_credit_receipts"):
            module.run(cfg)
    payback.process.assert_not_called()
    assert not (tmp_path / "reports").exists()


@pytest.fixture
def county_run(tmp_path, monkeypatch):
    source = tmp_path / "inputs" / SCENARIO / HOUSING / "alameda"
    source.mkdir(parents=True)
    (source / "weather_TMY_alameda.csv").touch()
    (source / f"combined_profiles_{SCENARIO}_alameda.csv").touch()
    monkeypatch.setattr(step, "prepare_weather_and_load", lambda *args: (object(), [1] * 8760))
    monkeypatch.setattr(step, "pv_timeseries_ac_kwh", lambda *args: [1] * 8760)
    # Hourly CSV writing is exercised by the representative county validation.
    monkeypatch.setattr(step, "_write_step9_outputs", lambda *args: None)
    return dict(base_input_dir=str(tmp_path / "inputs"), base_output_dir=str(tmp_path / "outputs"),
                scenario=SCENARIO, housing_type=HOUSING, counties=["alameda"])


def _short_solve(monkeypatch, capacity):
    tariff = TariffCatalog().bundle("PG&E", NBTScenario())
    times = pd.date_range("2026-01-01", periods=2, freq="h")
    terms = NBTAnnualTerms.from_tariff(tariff, times)
    inputs = CooptInputs([1, 1], [3, 0], list(terms.import_rates),
                         list(terms.export_rates), nbt_terms=terms)
    results = []

    def solve(county_inputs, **kwargs):
        assert len(county_inputs.load_kwh) == 8760
        result = _solve_lp(inputs, fixed_pv_kw=.623456789, fixed_batt_kwh=capacity,
                           weights=[365, 365], **kwargs)
        results.append(result)
        return result

    monkeypatch.setattr(step, "_solve_lp", solve)
    return results


@pytest.mark.parametrize("capacity", [2.9999, 3.00001])
@pytest.mark.parametrize("case", list(FederalCreditCase))
def test_saved_design_and_receipts_reconcile_without_capacity_rounding(
    county_run, monkeypatch, tmp_path, capacity, case,
):
    policy = PVStorageCreditPolicy(case, 1, .5)
    results = _short_solve(monkeypatch, capacity)
    step.process(**county_run, federal_credit_policy=policy, batt_capex_per_kw=25,
                 solver_options=SolverOptions(annual_cost_gap_usd=1e-5))
    output = tmp_path / "outputs" / SCENARIO / HOUSING
    saved = json.loads((output / "alameda/coopt_accounting_alameda.json").read_text())
    result = results[0]
    assert saved["schema_version"] == 1
    assert saved["scope"] == "solar_storage_only"
    assert saved["federal_credit_policy"] == {
        "case": case.value, "receipt_year": 1, "realization_fraction": .5,
    }
    assert saved["federal_rule_25d"]["fraction"] == .3
    assert saved["federal_rule_25d"]["minimum_storage_capacity_kwh"] == 3
    assert saved["cost_basis"] == "gross_with_one_time_federal_credits"
    assert saved["capital_assumptions"]["pv_usd_per_kw"] == SolarSystemAppliance.per_kw_cost()
    assert saved["capital_assumptions"]["battery_usd_per_kwh"] == BatteryStorageAppliance.per_kwh_cost()
    assert saved["capacities"]["pv_kw"] == result.pv_kw
    assert saved["capacities"]["battery_kwh"] == result.batt_kwh
    assert saved["federal_credit_receipts"] == asdict(result.federal_credit_receipts)
    eligible = case is not FederalCreditCase.NONE and capacity >= 3
    assert saved["federal_credit_receipts"]["amounts"]["storage_25d_usd"] == pytest.approx(
        .15 * saved["purchase_costs_usd"]["storage"] if eligible else 0,
    )
    csv = pd.read_csv(output / "CAPITAL_COSTS/electrified_assets.csv").iloc[0]
    assert csv["Solar Capacity (kW)"] == pytest.approx(result.pv_kw, abs=1e-12)
    assert csv["Battery Capacity (kWh)"] == pytest.approx(capacity, abs=1e-12)
    assert csv["Federal Credit Case"] == case.value
    assert csv["Capital Cost Basis"] == saved["cost_basis"]
    receipts = saved["federal_credit_receipts"]
    report = compute_eac_from_inputs(
        None, {"pv_capex": saved["purchase_costs_usd"]["pv"],
               "storage_capex": saved["purchase_costs_usd"]["storage"]},
        federal_credit_receipts=FederalCreditReceipts(
            HouseholdFederalCredits(**receipts["amounts"]), receipts["home_receipt_year"],
            receipts["vehicle_receipt_year"],
        ),
        annual_bill_electric=saved["annual_costs_usd"]["electricity_bill"],
    )
    assert report.total() == pytest.approx(saved["annual_costs_usd"]["total"], abs=1e-6)


def test_legacy_rerun_replaces_stale_credit_metadata(county_run, monkeypatch, tmp_path):
    _short_solve(monkeypatch, 3)
    step.process(**county_run, federal_credit_policy=POLICY)
    step.process(**county_run)
    output = tmp_path / "outputs" / SCENARIO / HOUSING
    saved = json.loads((output / "alameda/coopt_accounting_alameda.json").read_text())
    assert saved["cost_basis"] == "caller_supplied_unit_costs"
    assert saved["federal_credit_policy"] is None
    assert saved["federal_credit_receipts"] is None
    assert saved["federal_rule_25d"] is None
    csv = pd.read_csv(output / "CAPITAL_COSTS/electrified_assets.csv")
    assert len(csv) == 1
    assert csv.iloc[0]["Federal Credit Case"] == "not_configured"


@pytest.mark.parametrize("sweep", ["batt_capex_sweep", "batt_size_sweep", "pv_size_sweep", "pv_capex_sweep"])
def test_legacy_sweeps_fail_before_reading_or_writing(county_run, monkeypatch, tmp_path, sweep):
    with patch.object(step, "prepare_weather_and_load") as prepare:
        with pytest.raises(ValueError, match="not supported by legacy"):
            step.process(**county_run, federal_credit_policy=POLICY, **{sweep: [1]})
    prepare.assert_not_called()
    assert not (tmp_path / "outputs").exists()


@pytest.mark.parametrize("missing", ["weather_TMY_alameda.csv", f"combined_profiles_{SCENARIO}_alameda.csv"])
def test_missing_inputs_fail_instead_of_skipping(county_run, tmp_path, missing):
    (tmp_path / "inputs" / SCENARIO / HOUSING / "alameda" / missing).unlink()
    with pytest.raises(FileNotFoundError, match="Missing weather or load inputs"):
        step.process(**county_run, federal_credit_policy=POLICY)


@pytest.mark.parametrize("short", ["load", "pv"])
def test_short_profiles_fail_instead_of_skipping(county_run, monkeypatch, short):
    if short == "load":
        monkeypatch.setattr(step, "prepare_weather_and_load", lambda *args: (object(), [1] * 24))
    else:
        monkeypatch.setattr(step, "pv_timeseries_ac_kwh", lambda *args: [1] * 24)
    with pytest.raises(ValueError, match="requires 8760"):
        step.process(**county_run, federal_credit_policy=POLICY)


def test_empty_county_selection_fails(county_run, monkeypatch):
    monkeypatch.setattr(step, "get_counties", lambda *args: [])
    with pytest.raises(ValueError, match="at least one county"):
        step.process(**county_run, federal_credit_policy=POLICY)


def test_capacity_write_failure_is_not_reported_as_success(county_run, monkeypatch):
    _short_solve(monkeypatch, 3)
    def fail_write(*args, **kwargs):
        raise OSError("capacity output denied")
    monkeypatch.setattr(pd.DataFrame, "to_csv", fail_write)
    with pytest.raises(OSError, match="capacity output denied"):
        step.process(**county_run, federal_credit_policy=POLICY)


@pytest.mark.parametrize("contents", ["wrong_column\n1\n", "County\nalameda\nalameda\n"])
def test_invalid_saved_county_keys_are_not_silently_replaced(
    county_run, monkeypatch, tmp_path, contents,
):
    _short_solve(monkeypatch, 3)
    directory = tmp_path / "outputs" / SCENARIO / HOUSING / "CAPITAL_COSTS"
    directory.mkdir(parents=True)
    path = directory / "electrified_assets.csv"
    path.write_text(contents)
    with pytest.raises(ValueError, match="County"):
        step.process(**county_run, federal_credit_policy=POLICY)
    assert path.read_text() == contents


@pytest.mark.parametrize("declarations", [
    ["--federal-credit-case", "solar_storage_federal_credits"],
    ["--credit-receipt-year", "1", "--credit-realization-fraction", "1"],
    ["--federal-credit-case", "no_federal_credits", "--credit-receipt-year", "1"],
])
def test_cli_rejects_incomplete_declarations(monkeypatch, declarations):
    monkeypatch.setattr(sys, "argv", ["step9b", "--scenario", SCENARIO, *declarations])
    with patch.object(step, "process") as process:
        with pytest.raises(SystemExit) as exc:
            step.main()
    assert exc.value.code == 2
    process.assert_not_called()


@pytest.mark.parametrize("enabled", [False, True])
def test_cli_passes_explicit_policy_and_separate_output_root(monkeypatch, enabled):
    argv = ["step9b", "--scenario", SCENARIO, "--base-input-dir", "inputs",
            "--base-output-dir", "outputs", "--counties", "alameda"]
    if enabled:
        argv += ["--federal-credit-case", "solar_storage_federal_credits",
                 "--credit-receipt-year", "1", "--credit-realization-fraction", ".5"]
    monkeypatch.setattr(sys, "argv", argv)
    with patch.object(step, "process") as process:
        step.main()
    kwargs = process.call_args.kwargs
    assert kwargs["base_input_dir"] == "inputs"
    assert kwargs["base_output_dir"] == "outputs"
    assert kwargs["federal_credit_policy"] == (POLICY if enabled else None)
