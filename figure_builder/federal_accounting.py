"""Validate saved solar/storage accounting and explicit household credit inputs."""
from __future__ import annotations

from dataclasses import asdict
import json
import math
from numbers import Real
from pathlib import Path

from appliances.federal_credits import FEDERAL_ITC_25D
from evaluations.eac import compute_eac_from_inputs
from evaluations.federal_credits import (
    FederalCreditCase, HouseholdCreditDeclaration, PVStorageCreditPolicy,
)


def load_credit_declarations(path, expected_households):
    """Require one explicit declaration per requested scenario/county pair."""
    payload = json.loads(Path(path).read_text())
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "households"}:
        raise ValueError("Credit declarations require schema_version and households")
    if payload["schema_version"] != 1 or not isinstance(payload["households"], list):
        raise ValueError("Unsupported household credit declaration schema")
    declarations = {}
    try:
        for row in payload["households"]:
            fields = dict(row)
            key = (fields.pop("scenario"), fields.pop("county_slug"))
            if key in declarations:
                raise ValueError(f"Duplicate household credit declaration: {key}")
            policy = dict(fields.pop("pv_storage_policy"))
            policy["case"] = FederalCreditCase(policy["case"])
            declarations[key] = HouseholdCreditDeclaration(
                pv_storage_policy=PVStorageCreditPolicy(**policy), **fields,
            )
    except (KeyError, TypeError) as exc:
        raise ValueError(f"Missing or malformed household credit declaration: {exc}") from exc
    if set(declarations) != set(expected_households):
        raise ValueError("Credit declarations must exactly cover requested households")
    policies = [value.pv_storage_policy for value in declarations.values()]
    if not policies or any(policy != policies[0] for policy in policies):
        raise ValueError("Matched households require the same solar/storage credit policy")
    return declarations


def _number(value):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError("Saved accounting values must be finite numbers")
    return float(value)


def _close(actual, expected, label, tolerance=1e-6):
    if abs(_number(actual) - _number(expected)) > tolerance:
        raise ValueError(f"Saved federal accounting does not reconcile: {label}")


def validate_saved_accounting(accounting, solver, design, declaration, ledger, *,
                              scenario, county, housing_type):
    """Check identities, costs, receipts, credit bases, and the solver certificate.

    The matched publication comparison uses its established 7%, 25-year/15-year
    framing and zero degradation charge. Other framings need an explicit extension.
    """
    try:
        _validate_saved_accounting(accounting, solver, design, declaration, ledger,
                                   scenario, county, housing_type)
    except (KeyError, TypeError) as exc:
        raise ValueError(f"Missing or malformed saved federal accounting: {exc}") from exc


def _validate_saved_accounting(a, solver, design, declaration, ledger, scenario, county, housing):
    identity = {"schema_version": 1, "scope": "solar_storage_only", "scenario": scenario,
                "county": county, "housing_type": housing,
                "cost_basis": "gross_with_one_time_federal_credits"}
    if any(a[key] != value for key, value in identity.items()):
        raise ValueError("Saved federal accounting identity does not match the requested household")
    policy = declaration.pv_storage_policy
    expected_policy = asdict(policy) | {"case": policy.case.value}
    saved_policy = a["federal_credit_policy"]
    saved_case = FederalCreditCase(saved_policy["case"])
    credited_cases = {FederalCreditCase.PV_STORAGE, FederalCreditCase.ALL}
    # Appliance credits are constants in a fixed household's sizing objective.
    # Reuse the same optimized design between the two credited cases.
    comparable_policy = dict(saved_policy)
    if saved_case in credited_cases and policy.case in credited_cases:
        comparable_policy["case"] = policy.case.value
    if comparable_policy != expected_policy:
        raise ValueError("Saved optimizer policy differs from the household credit declaration")
    for key in ("fraction", "minimum_storage_capacity_kwh"):
        _close(a["federal_rule_25d"][key], getattr(FEDERAL_ITC_25D, key), key, 1e-12)
    capital = a["capital_assumptions"]
    if any(capital[key] != value for key, value in
           (("discount_rate", .07), ("study_years", 25), ("battery_life_years", 15))):
        raise ValueError("Federal matched comparison requires 7%, a 25-year study and 15-year battery")
    capacities, purchase, annual = a["capacities"], a["purchase_costs_usd"], a["annual_costs_usd"]
    for block in (capital, capacities, purchase, annual):
        if any(_number(value) < 0 for value in block.values()):
            raise ValueError("Saved federal costs, capacities, and assumptions must be nonnegative")
    for key, column in (("pv_kw", "Solar Capacity (kW)"),
                        ("battery_kwh", "Battery Capacity (kWh)"),
                        ("battery_kw", "Battery Power Capacity (kW)")):
        _close(capacities[key], design[column], column, 1e-10)
    if (design["Capital Cost Basis"] != a["cost_basis"]
            or design["Federal Credit Case"] != saved_case.value):
        raise ValueError("Capacity summary has a different federal credit case or cost basis")
    _close(purchase["pv"], capacities["pv_kw"] * capital["pv_usd_per_kw"], "PV purchase cost")
    _close(purchase["storage"], capacities["battery_kwh"] * capital["battery_usd_per_kwh"]
           + capacities["battery_kw"] * capital["battery_usd_per_kw"], "storage purchase cost")
    receipts = policy.receipts_for_system(
        pv_gross_usd=purchase["pv"], storage_gross_usd=purchase["storage"],
        storage_capacity_kwh=capacities["battery_kwh"],
    )
    if a["federal_credit_receipts"] != asdict(receipts):
        raise ValueError("Saved solar/storage credit receipts do not match the selected design")
    if annual["degradation"] != 0 or a["dispatch_assumptions"]["battery_degradation_usd_per_kwh"] != 0:
        raise ValueError("Federal matched comparison requires zero degradation charge")
    replay = compute_eac_from_inputs(
        None, {"pv_capex": purchase["pv"], "storage_capex": purchase["storage"]},
        federal_credit_receipts=receipts, annual_bill_electric=annual["electricity_bill"],
    )
    _close(replay.capex_pv + replay.capex_storage, annual["capital"], "annual capital cost")
    _close(replay.total(), annual["total"], "annual solar/storage objective")
    _close(annual["total"], design["Coopt Total Cost"], "capacity summary objective", .000051)
    gap = _number(solver["optimality_gap_usd"])
    tolerance = _number(solver["options"]["annual_cost_gap_usd"])
    if not 0 <= gap <= tolerance + 1e-6 or tolerance < 0:
        raise ValueError("Invalid saved federal solver cost gap")
    _close(annual["total"] - _number(solver["lower_bound_usd"]), gap, "solver bound")
    _close(gap, design["Solver Cost Gap (USD/year)"], "capacity summary solver gap")
    _close(tolerance, design["Solver Cost Tolerance (USD/year)"], "solver cost tolerance")
    for key, column in (("utility", "Utility"), ("import_plan", "Import Tariff Plan"),
                        ("import_source_id", "Import Tariff Source ID"),
                        ("snapshot_date", "Import Tariff Snapshot As Of"),
                        ("billing_year", "NBT Billing Year"), ("nbt_vintage", "NBT Interconnection Vintage")):
        if a["tariff"][key] != design[column]:
            raise ValueError(f"Saved federal tariff differs from capacity summary: {key}")
    for key, column in (("max_battery_kwh", "Battery Capacity Upper Bound (kWh)"),
                        ("allow_grid_charging", "Allow Grid Charging"),
                        ("allow_battery_export", "Allow Battery Export")):
        if a["dispatch_assumptions"][key] != design[column]:
            raise ValueError(f"Saved federal dispatch setting differs: {key}")
    # Eligible cost is declared, but cannot exceed the matching gross equipment cost.
    selected = ledger[(ledger.county_slug == county)
                      & (ledger.incentive_scenario == "full_incentives")
                      & (ledger.appliance_category == "electric")]
    for kind, basis in (("heating", declaration.space_heat_pump_eligible_basis_usd),
                        ("hot_water", declaration.water_heat_pump_eligible_basis_usd)):
        if basis > selected.loc[selected.appliance_type == kind, "base_cost"].sum() + 1e-8:
            raise ValueError(f"Declared eligible {kind} basis exceeds its gross household cost")
    if declaration.eligible_vehicle_credit_usd > 0 and not (selected.appliance_type == "vehicle_charging").any():
        raise ValueError("Declared EV credit requires an electric vehicle in the household ledger")
    # Validate receipt times and household cost bounds even for excluded families.
    household_receipts = declaration.receipts_for_system(
        pv_gross_usd=0, storage_gross_usd=0, storage_capacity_kwh=0,
    )
    compute_eac_from_inputs(
        ledger[(ledger.county_slug == county) & (ledger.incentive_scenario == "full_incentives")],
        None, federal_credit_receipts=household_receipts,
    )
