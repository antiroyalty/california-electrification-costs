"""Explain saved pilot costs without changing household inputs or optimizing.

Run with --pilot-dir and a new --output-dir. Each component uses the saved
gross-cost ledger, one explicit incentive row, and independently discounted
cash flows. Missing or inconsistent records fail before figures are written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import pandas as pd


CREDIT_CASES = (
    "no_federal_credits", "solar_storage_federal_credits",
    "all_modeled_federal_credits",
)
SCENARIOS = {
    "gas": "baseline_ice_car_coopt", "electric": "full_electric_ev_coopt",
}
COUNTIES = ("alameda", "los-angeles", "san-diego")
PART_LABELS = {
    "heating": "Space heating",
    "hot_water": "Water heating",
    "cooking": "Cooking",
    "vehicle": "Vehicle + charger",
    "other_equipment": "Other equipment",
    "solar_storage": "Solar/storage",
    "electricity": "Electricity bill",
    "gas": "Gas bill",
    "gasoline": "Gasoline",
    "maintenance": "Vehicle maintenance",
    "insurance": "Vehicle insurance",
    "heat_pump_credit": "Heat-pump credit",
    "ev_credit": "EV credit",
}


def finite(value, label, *, nonnegative=True):
    value = float(value)
    if not math.isfinite(value) or (nonnegative and value < 0):
        raise ValueError(f"Invalid {label}: {value}")
    return value


def annual_factor(years, rate=.07):
    """Annual expense whose discounted sum equals one initial dollar."""
    years = finite(years, "service life")
    if years <= 0 or years != int(years):
        raise ValueError("Expected a positive whole-year service life")
    rate = finite(rate, "discount rate")
    return 1 / sum((1 + rate) ** -year for year in range(1, int(years) + 1))


def reconcile(actual, expected, label):
    if not math.isclose(actual, expected, rel_tol=0, abs_tol=1e-7):
        raise ValueError(f"{label} does not reconcile: {actual} != {expected}")


def household_components(row, ledger):
    """Return annual USD components for one saved household/solar choice."""
    household = row["case"].split("_")[0]
    if household not in SCENARIOS or row["scenario"] != SCENARIOS[household]:
        raise ValueError("Household and scenario do not match")
    selected = ledger[
        (ledger.county_slug == row["county_slug"])
        & (ledger.incentive_scenario == "full_incentives")
    ].copy()
    required = {"heating", "hot_water", "cooking", "misc", "appliances",
                "vehicle_fuel" if household == "gas" else "vehicle_charging"}
    if (set(selected.appliance_type) != required
            or selected.appliance_type.duplicated().any()):
        raise ValueError("Expected exactly one selected row per household appliance")
    if not (selected.scenario == row["scenario"]).all():
        raise ValueError("Ledger scenario does not match")
    parts = dict.fromkeys(PART_LABELS, 0.)
    gross_by_category = dict(gas=0., electric=0.)
    for item in selected.to_dict("records"):
        kind = item["appliance_type"]
        cost = finite(item["base_cost"], "gross equipment cost")
        annual = cost * annual_factor(item["lifetime_years"])
        gross_by_category[item["appliance_category"]] += annual
        if kind in ("vehicle_fuel", "vehicle_charging"):
            parts["vehicle"] += annual
            parts["maintenance"] = finite(item["annual_maintenance_cost"], "maintenance")
            parts["insurance"] = finite(item["annual_insurance_cost"], "insurance")
            # EV electricity is already in the home bill. The EV ledger has no fuel field.
            parts["gasoline"] = (finite(item["annual_fuel_cost"], "gasoline")
                                 if kind == "vehicle_fuel" else 0.)
            vehicle_om = parts["maintenance"] + parts["insurance"] + parts["gasoline"]
            reconcile(vehicle_om, finite(item["annual_operating_cost"], "vehicle O&M"), "Ledger O&M")
            reconcile(vehicle_om, finite(row["vehicle_om"], "reported O&M"), "Reported O&M")
        else:
            parts[kind if kind in ("heating", "hot_water", "cooking") else "other_equipment"] += annual
    parts["heat_pump_credit"] = (
        -finite(row["heat_pumps_25c_usd"], "heat-pump credit") / 1.07 * annual_factor(25)
    )
    parts["ev_credit"] = -finite(row["vehicle_30d_usd"], "EV credit") * annual_factor(25)
    reconcile(gross_by_category["gas"], finite(row["capex_gas"], "gas capital"), "Gas capital")
    reconcile(gross_by_category["electric"] + parts["heat_pump_credit"] + parts["ev_credit"],
              finite(row["capex_electric"], "electric capital"), "Electric capital")
    parts["solar_storage"] = (finite(row["capex_pv"], "solar capital")
                              + finite(row["capex_storage"], "storage capital"))
    parts["electricity"] = finite(row["annual_bill_electric"], "electricity bill")
    parts["gas"] = finite(row["annual_bill_gas"], "gas bill")
    reconcile(sum(parts.values()), finite(row["total_eac"], "household total"), "Household total")
    return parts


def input_identity(path):
    return dict(path=str(path.resolve()), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def fixed_battery_lower_bound(inputs, *, battery_kwh=3., battery_usd_per_kwh=1460.64):
    """Capture the first relaxed model's certificate, not a physical design.

    The existing solver initially omits meter-direction restrictions. Its lower
    bound therefore also bounds every physically valid fixed-battery design.
    Stop after that solve, without changing any model coefficient or constraint.
    This diagnostic hook avoids adding a new production optimization mode.
    """
    from unittest.mock import patch
    from evaluations.federal_credits import FederalCreditCase, PVStorageCreditPolicy
    from pipeline.solver import SolverOptions, SolverRun
    from pipeline.steps.step9b_cooptimize_core import _solve_lp

    class Captured(Exception):
        def __init__(self, certificate):
            self.certificate = certificate

    original_solve = SolverRun.solve_round

    def capture(run, problem):
        if run.round_count != 0:
            raise RuntimeError("Expected the initial relaxed model")
        raise Captured(original_solve(run, problem))

    with patch.object(SolverRun, "solve_round", capture):
        try:
            _solve_lp(inputs, fixed_batt_kwh=battery_kwh, c_pv_kw=3300,
                      c_batt_kwh=battery_usd_per_kwh,
                      federal_credit_policy=PVStorageCreditPolicy(FederalCreditCase.PV_STORAGE, 1, 1),
                      solver_options=SolverOptions(annual_cost_gap_usd=5, time_limit_seconds=60))
        except Captured as result:
            return result.certificate
    raise RuntimeError("No relaxed cost certificate was captured")


def analyze(pilot_dir):
    """Reconcile all 36 cells; report electric minus gas component differences."""
    records, differences, sources = [], [], []
    for credit_case in CREDIT_CASES:
        sizing_case = CREDIT_CASES[1] if credit_case == CREDIT_CASES[2] else credit_case
        path = pilot_dir / f"{credit_case}.csv"
        frame = pd.read_csv(path)
        sources.append(input_identity(path))
        expected = {(county, household + choice) for county in COUNTIES
                    for household in SCENARIOS for choice in ("_no_solar", "_optimized")}
        if set(zip(frame.county_slug, frame["case"])) != expected or len(frame) != len(expected):
            raise ValueError("Expected four unique household choices per pilot county")
        ledgers = {}
        for household, scenario in SCENARIOS.items():
            path = (pilot_dir / sizing_case / "loadprofiles/capital_costs"
                    / f"capital_costs_{scenario}_single_family_detached.csv")
            ledgers[household] = pd.read_csv(path)
            sources.append(input_identity(path))
        totals = {}
        for row in frame.to_dict("records"):
            household = row["case"].split("_")[0]
            parts = household_components(row, ledgers[household])
            totals[row["county_slug"], row["case"]] = parts
            records.append(dict(credit_case=credit_case, county=row["county_slug"],
                                household_choice=row["case"], **parts, total=sum(parts.values())))
        for county in COUNTIES:
            electric, gas = (totals[county, h + "_optimized"] for h in ("electric", "gas"))
            diff = {k: electric[k] - gas[k] for k in PART_LABELS}
            differences.append(dict(credit_case=credit_case, county=county,
                                    **diff, total=sum(diff.values())))
    return pd.DataFrame(records), pd.DataFrame(differences), sources


def plot_breakdown(differences, output_dir):
    """One waterfall per county, with common scales and explicit cost signs."""
    import matplotlib.pyplot as plt
    import numpy as np

    labels = ["Vehicle +\ncharger", "Space\nheating", "Water\nheating", "Cooking", "Solar/\nstorage",
              "Energy\nbills", "Maintenance\n+ insurance", "Heat-pump\n+ EV credits", "Net annual\ndifference"]
    fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True, sharey=True)
    selected = differences[differences.credit_case == CREDIT_CASES[2]].set_index("county")
    for ax, county in zip(axes, COUNTIES):
        r = selected.loc[county]
        values = [r.vehicle, r.heating, r.hot_water, r.cooking, r.solar_storage,
                  r.electricity + r.gas + r.gasoline, r.maintenance + r.insurance,
                  r.heat_pump_credit + r.ev_credit]
        reconcile(sum(values), r.total, "Plotted components")
        running = 0.
        for i, value in enumerate(values):
            ax.bar(i, abs(value), bottom=min(running, running + value), width=.66,
                   color="#bd5845" if value > 0 else "#258577")
            ax.text(i, max(running, running + value) + 95, f"{value:+,.0f}", ha="center", fontsize=10)
            running += value
            ax.plot([i+.33, i+.67], [running, running], color="0.6", linewidth=.7)
        ax.bar(8, r.total, width=.66, color="#293c58")
        ax.text(8, r.total + 95, f"+${r.total:,.0f}", ha="center", fontweight="bold")
        ax.set_title(county.replace("-", " ").title(), loc="left", fontsize=13)
        ax.axhline(0, color="0.5", linewidth=.7)
        ax.annotate("Equal total cost", xy=(.5, 0),
                    xycoords=("axes fraction", "data"), xytext=(0, 6),
                    textcoords="offset points", ha="center", va="bottom",
                    fontsize=9, color="0.35")
        ax.set_ylim(0, 4800)
        ax.set_ylabel("Annual cost difference\nversus gas/ICE ($/year)")
        ax.spines[["top", "right"]].set_visible(False)
    axes[-1].set_xticks(np.arange(9), labels)
    fig.suptitle("Higher equipment costs outweigh energy savings in three California counties",
                 fontsize=17, y=.98)
    fig.text(.5, .945, "Electric/EV minus gas/ICE · both optimize solar/storage · "
             "all modeled federal credits", ha="center", fontsize=11)
    fig.text(.07, .025, "Red adds cost; green reduces cost. Solar/storage includes its credits.\n"
             "Fixed 2026 NBT tariffs; full federal credit realization; other rebates "
             "and away-from-home charging excluded.", fontsize=10)
    fig.tight_layout(rect=(0, .065, 1, .925), h_pad=1.8)
    for extension in ("png", "svg"):
        fig.savefig(output_dir / f"household_cost_breakdown.{extension}", dpi=170)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    components, differences, sources = analyze(args.pilot_dir)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    components.to_csv(args.output_dir / "household_components.csv", index=False)
    differences.to_csv(args.output_dir / "cost_differences.csv", index=False)
    plot_breakdown(differences, args.output_dir)
    manifest = dict(validated_household_cells=len(components), sources=sources,
                    driver=input_identity(Path(__file__)), sign="electric minus gas",
                    assumptions="7% discount; appliance service-life annualization; "
                    "one initial federal credit over 25 years")
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(differences[differences.credit_case == CREDIT_CASES[2]].to_string(index=False))


if __name__ == "__main__":
    main()
