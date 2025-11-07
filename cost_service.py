import sys
import argparse
import os
import pandas as pd

from scenarios import SCENARIOS

import step1_identify_suitable_buildings as IdentifySuitableBuildings
import step2_pull_buildings as PullBuildings
import step3_build_electricity_load_profiles as BuildElectricityLoadProfiles
import step4_build_gas_load_profiles as BuildGasLoadProfiles
import step5_convert_gas_appliances_to_electrical_appliances as ConvertGasToElectric
import step6_build_electric_vehicle_load_profiles as BuildElectricVehicleLoadProfiles
import step7_combine_real_and_simulated_electricity_loads as CombineRealAndSimulatedProfiles
import step8_get_weather_files as WeatherFiles

# Historical step 9 implementations (toggle as needed):
# import step9_run_sam_model_for_solar_storage as RunSamModelForSolarStorage  # Pvwatts + Battwatts
# import step9_pvsamv1_battery as RunSamModelForSolarStorage                 # Pvsamv1 integrated battery
# import step9_solar_storage_custom_dispatch as RunSamModelForSolarStorage   # Pvsamv1 PV + custom dispatch
import step9_my_own_solar_storage as RunSamModelForSolarStorage             # DIY PV + custom dispatch

import step10_get_loads_for_rates as GetLoadsForRates
import step11_evaluate_gas_rates as EvaluateGasRates
import step12_evaluate_electricity_rates as EvaluateElectricityRates
import step13_combine_total_annual_costs as CombineTotalAnnualCosts
import step14_build_capital_costs_lifetimes_incentives as BuildCapitalCostsLifetimesIncentives
import step15_payback_periods as PaybackPeriods
import step16_display_key_metrics_maps as DisplayKeyMetricsMaps

from helpers.main_helpers import (
    norcal_counties,
    socal_counties,
    central_counties,
    git_short_sha,
)
from helpers.plot_scenario_comparison_helper import (
    collect_eac_components,
    collect_eac_components_by_county,
    plot_eac_stacked_bar,
)
from step20_no_solar_storage_electrification import (
    collect_eac_no_pv,
    collect_eac_no_pv_by_county,
    plot_eac_no_pv_stacked_bar,
)
from step21_compare_eac_with_vs_without import plot_grouped_eac

import step9_my_own_solar_storage as Step9


class CostService:
    def __init__(self, scenario, housing_type, counties, rate_plans, input_dir, output_dir):
        self.scenario = scenario
        self.housing_type = housing_type
        self.counties = counties
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.desired_rate_plans = rate_plans

    def log_step(self, step: int):
        print("-" * 15, f" Step {step} ", "-" * 15)

    def run(self):
        # Core pipeline
        self.log_step(1)
        IdentifySuitableBuildings.process(self.scenario, self.housing_type, output_base_dir="data", target_counties=self.counties, force_recompute=False)

        self.log_step(2)
        PullBuildings.process(self.scenario, self.housing_type, self.counties, output_base_dir="data", download_new_files=False)

        self.log_step(3)
        BuildElectricityLoadProfiles.process(self.scenario, SCENARIOS[self.scenario], self.housing_type, self.counties, "data", "data/loadprofiles", force_recompute=False)

        self.log_step(4)
        BuildGasLoadProfiles.process("data", "data/loadprofiles", self.scenario, SCENARIOS, self.housing_type, self.counties, force_recompute=False)

        self.log_step(5)
        ConvertGasToElectric.process("data/loadprofiles", "data/loadprofiles", self.counties, self.scenario, [self.housing_type], force_recompute=False)

        self.log_step(6)
        BuildElectricVehicleLoadProfiles.process("data", "data/loadprofiles", self.scenario, SCENARIOS[self.scenario], [self.housing_type], self.counties, force_recompute=False)

        self.log_step(7)
        CombineRealAndSimulatedProfiles.process("data/loadprofiles", "data/loadprofiles", self.scenario, [self.housing_type], self.counties, force_recompute=False)

        self.log_step(8)
        WeatherFiles.process("data/loadprofiles", "data/loadprofiles", self.scenario, [self.housing_type], 2018, self.counties)

        self.log_step(9)
        RunSamModelForSolarStorage.process("data/loadprofiles", "data/loadprofiles", self.scenario, self.housing_type, self.counties, force_recompute=True)

        self.log_step(10)
        GetLoadsForRates.process("data/loadprofiles", "data/loadprofiles", self.scenario, [self.housing_type], self.counties)

        self.log_step(11)
        EvaluateGasRates.process("data/loadprofiles", "data/loadprofiles", self.scenario, [self.housing_type], self.counties)

        self.log_step(12)
        EvaluateElectricityRates.process("data/loadprofiles", "data/loadprofiles", self.scenario, self.housing_type, self.counties)

        self.log_step(13)
        CombineTotalAnnualCosts.process("data/loadprofiles", "data/loadprofiles", self.scenario, [self.housing_type], self.counties)

        self.log_step(14)
        BuildCapitalCostsLifetimesIncentives.process("data/loadprofiles", "data/loadprofiles", self.scenario, self.housing_type, self.counties)

        self.log_step(15)
        PaybackPeriods.process("data/loadprofiles", self.scenario, self.housing_type, self.counties)

        self.log_step(16)
        # DisplayKeyMetricsMaps.process("data/loadprofiles", "data/loadprofiles", self.scenario, self.housing_type, self.counties, self.desired_rate_plans)

        # Consolidated comparisons and EAC summaries (Steps 18–21)
        base_input_dir = self.output_dir
        output_dir = os.path.join("analysis_results")
        os.makedirs(output_dir, exist_ok=True)
        sha = git_short_sha()

        # Assumptions summary
        print("\nAssumptions — " + self._summarize_dispatch_and_sizing())

        # Step 18: Cross-scenario EAC (NEM3 by default)
        self.log_step(18)
        scenarios_18 = self._scenario_list_for_comparisons()
        plan_pref = list({v.get('electricity') for v in self.desired_rate_plans.values() if isinstance(v, dict) and v.get('electricity')})
        eac_df = collect_eac_components(
            base_input_dir,
            self.housing_type,
            scenarios_18,
            self.counties,
            incentive="full_incentives",
            agg="mean",
            electricity_plan_preference=plan_pref,
            electricity_variant="nem3",
        )
        comp_cols = ["capex_pv", "capex_storage", "capex_electric", "capex_gas", "vehicle_om"]
        if "annual_bill_electric" in eac_df.columns and "annual_bill_gas" in eac_df.columns:
            bill_col = eac_df["annual_bill_electric"].fillna(0) + eac_df["annual_bill_gas"].fillna(0)
        else:
            bill_col = eac_df.get("annual_bill_with_solar", pd.Series([0] * len(eac_df)))
        eac_df["total_eac"] = eac_df[comp_cols].sum(axis=1) + bill_col
        eac_df.to_csv(os.path.join(output_dir, f"step18_eac_summary_g{sha}.csv"), index=False)
        fig18 = plot_eac_stacked_bar(eac_df, scenario_order=scenarios_18)
        fig18.savefig(os.path.join(output_dir, f"step18_eac_stacked_bar_g{sha}.png"), dpi=150, bbox_inches="tight")
        if not eac_df.empty:
            top = eac_df.sort_values("total_eac").head(5)[["scenario", "total_eac"]]
            print("Cross-scenario EAC (with PV) — lowest totals:")
            for _, r in top.iterrows():
                print(f"  {r['scenario']}: ${r['total_eac']:.0f}/yr")
        # Per-county EAC (NEM3 and retail)
        by_cty_nem3 = collect_eac_components_by_county(
            base_input_dir,
            self.housing_type,
            scenarios_18,
            self.counties,
            incentive="full_incentives",
            electricity_plan_preference=plan_pref,
            electricity_variant="nem3",
        )
        by_cty_retail = collect_eac_components_by_county(
            base_input_dir,
            self.housing_type,
            scenarios_18,
            self.counties,
            incentive="full_incentives",
            electricity_plan_preference=plan_pref,
            electricity_variant="retail",
        )
        by_cty_nem3.to_csv(os.path.join(output_dir, f"step18_eac_by_county_nem3_g{sha}.csv"), index=False)
        by_cty_retail.to_csv(os.path.join(output_dir, f"step18_eac_by_county_retail_g{sha}.csv"), index=False)

        # Step 19: EV vs ICE comparison
        self.log_step(19)
        pair = ["baseline_ice_car", "baseline_ev_car"]
        eac19 = collect_eac_components(
            base_input_dir,
            self.housing_type,
            pair,
            self.counties,
            incentive="full_incentives",
            agg="mean",
            electricity_plan_preference=plan_pref,
            electricity_variant="nem3",
        )
        if "annual_bill_electric" in eac19.columns and "annual_bill_gas" in eac19.columns:
            eac19["total_eac"] = (
                eac19[["capex_pv", "capex_storage", "capex_electric", "capex_gas", "vehicle_om"]].sum(axis=1)
                + eac19["annual_bill_electric"].fillna(0) + eac19["annual_bill_gas"].fillna(0)
            )
        else:
            eac19["total_eac"] = (
                eac19[["capex_pv", "capex_storage", "capex_electric", "capex_gas", "vehicle_om", "annual_bill_with_solar"]].sum(axis=1)
            )
        fig19 = plot_eac_stacked_bar(eac19, scenario_order=pair, title=f"All-in Annualized Cost — {pair[0]} vs {pair[1]}")
        fig19.savefig(os.path.join(output_dir, f"step19_eac_stacked_bar_{pair[0]}_vs_{pair[1]}_g{sha}.png"), dpi=150, bbox_inches="tight")
        ice_val = float(eac19[eac19["scenario"] == pair[0]]["total_eac"].values[0])
        ev_val = float(eac19[eac19["scenario"] == pair[1]]["total_eac"].values[0])
        delta_19 = ev_val - ice_val
        print(f"EV vs ICE annualized cost: {pair[1]} is ${abs(delta_19):.0f}/yr {'higher' if delta_19 > 0 else 'lower'} than {pair[0]}")
        by_cty = collect_eac_components_by_county(
            base_input_dir,
            self.housing_type,
            pair,
            self.counties,
            incentive="full_incentives",
            electricity_plan_preference=plan_pref,
            electricity_variant="nem3",
        )
        by_cty = by_cty.copy()
        by_cty["total_eac"] = (
            by_cty[["capex_pv", "capex_storage", "capex_electric", "capex_gas", "vehicle_om"]].sum(axis=1)
            + by_cty["annual_bill_electric"].fillna(0) + by_cty["annual_bill_gas"].fillna(0)
        )
        a = by_cty[by_cty["scenario"] == pair[0]][["county_slug", "total_eac"]].rename(columns={"total_eac": f"{pair[0]}_total"})
        b = by_cty[by_cty["scenario"] == pair[1]][["county_slug", "total_eac"]].rename(columns={"total_eac": f"{pair[1]}_total"})
        m = a.merge(b, on="county_slug", how="inner")
        m["delta_ev_minus_ice"] = m[f"{pair[1]}_total"] - m[f"{pair[0]}_total"]
        m.to_csv(os.path.join(output_dir, f"step19_ev_vs_ice_by_county_g{sha}.csv"), index=False)

        # Step 20: No-solar EAC for context (current scenario)
        self.log_step(20)
        scen20 = [self.scenario]
        eac20 = collect_eac_no_pv(
            base_input_dir,
            self.housing_type,
            scen20,
            self.counties,
            incentive="full_incentives",
            discount_rate=0.07,
            agg="mean",
        )
        eac20.to_csv(os.path.join(output_dir, f"step20_eac_no_pv_summary_g{sha}.csv"), index=False)
        fig20 = plot_eac_no_pv_stacked_bar(eac20, scenario_order=scen20, title=f"All-in Annualized Cost (No Solar + Storage) — {self.scenario}")
        fig20.savefig(os.path.join(output_dir, f"step20_eac_no_pv_stacked_bar_g{sha}.png"), dpi=150, bbox_inches="tight")

        # Step 21: With vs Without PV for selected scenario
        self.log_step(21)
        with_df = collect_eac_components(
            base_input_dir,
            self.housing_type,
            [self.scenario],
            self.counties,
            incentive="full_incentives",
            agg="mean",
            electricity_plan_preference=plan_pref,
            electricity_variant="nem3",
        )
        no_df = collect_eac_no_pv(
            base_input_dir,
            self.housing_type,
            [self.scenario],
            self.counties,
            incentive="full_incentives",
            discount_rate=0.07,
            agg="mean",
        )
        a = with_df.copy()
        if "annual_bill_electric" not in a.columns and "annual_bill_with_solar" in a.columns:
            a["annual_bill_electric"] = a["annual_bill_with_solar"]
            a["annual_bill_gas"] = 0.0
        a["variant"] = "with_pv"
        b = no_df.copy()
        if "annual_bill_electric" not in b.columns and "annual_bill_default" in b.columns:
            b["annual_bill_electric"] = b["annual_bill_default"]
            b["annual_bill_gas"] = 0.0
        for c in ["capex_pv", "capex_storage"]:
            if c not in b.columns:
                b[c] = 0.0
        b["variant"] = "no_pv"
        keep = [
            "scenario",
            "variant",
            "capex_pv",
            "capex_storage",
            "capex_electric",
            "capex_gas",
            "vehicle_om",
            "annual_bill_electric",
            "annual_bill_gas",
        ]
        merged = pd.concat([a[keep], b[keep]], ignore_index=True)
        merged.to_csv(os.path.join(output_dir, f"step21_eac_with_vs_without_g{sha}.csv"), index=False)
        fig21 = plot_grouped_eac(merged, scenario_order=[self.scenario], county_label="All Counties")
        fig21.savefig(os.path.join(output_dir, f"step21_eac_with_vs_without_g{sha}.png"), dpi=150, bbox_inches="tight")
        def _tot(row: pd.Series) -> float:
            return float(row[["capex_pv", "capex_storage", "capex_electric", "capex_gas", "vehicle_om"]].sum() + float(row.get("annual_bill_electric", 0.0)) + float(row.get("annual_bill_gas", 0.0)))
        t_no = _tot(merged[(merged["scenario"] == self.scenario) & (merged["variant"] == "no_pv")].iloc[0])
        t_yes = _tot(merged[(merged["scenario"] == self.scenario) & (merged["variant"] == "with_pv")].iloc[0])
        d = t_yes - t_no
        pct = (d / t_no) * 100 if t_no else 0.0
        print(f"With PV+storage total EAC is ${abs(d):.0f}/yr ({abs(pct):.1f}%) {'LOWER' if d < 0 else 'HIGHER'} than electrification-only for {self.scenario}.")

    def _scenario_list_for_comparisons(self):
        preferred = [
            "baseline",
            "induction_stove",
            "water_heating",
            "heat_pump",
            "heat_pump_and_induction_stove",
            "heat_pump_and_induction_stove_and_water_heating",
            "baseline_ice_car",
            "baseline_ev_car",
            "full_electric_ev",
        ]
        return [s for s in preferred if s in SCENARIOS]

    def _summarize_dispatch_and_sizing(self):
        mode = "dynamic PV-only" if getattr(Step9, "USE_DYNAMIC_DISPATCH", False) else "classic 4–9pm"
        sizing = (
            "EAC-optimal per county" if getattr(Step9, "USE_EAC_OPTIMAL_SIZING", False)
            else f"fraction of annual-match (PV_SIZE_FRACTION={getattr(Step9, 'PV_SIZE_FRACTION', 'n/a')})"
        )
        batt = getattr(Step9, "BATTERY_CAPACITY_KWH", None)
        batt_str = f", default battery ≈{batt} kWh" if batt else ""
        plans = sorted({v.get('electricity') for v in self.desired_rate_plans.values() if isinstance(v, dict) and v.get('electricity')})
        plan_str = f"; Electricity plan preference: {', '.join(plans)}" if plans else ""
        return f"Dispatch: {mode}; Sizing: {sizing}{batt_str}{plan_str}; Billing variant: NEM3 for with-solar"


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Run cost analysis for residential electrification scenarios in California",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Available scenarios:
  - baseline
  - heat_pump
  - induction_stove
  - heat_pump_and_induction_stove
  - water_heating
  - heat_pump_and_induction_stove_and_water_heating

Example usage:
  python3 cost_service.py heat_pump_and_induction_stove
  python3 cost_service.py water_heating
  python3 cost_service.py baseline""",
    )
    parser.add_argument("scenario", help="Electrification scenario to analyze")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()
    scenario = args.scenario

    if scenario not in SCENARIOS:
        print(f"Error: Unknown scenario '{scenario}'")
        print(f"Available scenarios: {', '.join(SCENARIOS.keys())}")
        sys.exit(1)

    housing_type = "single-family-detached"
    input_dir = "data"
    output_dir = "data/loadprofiles"

    rate_plans = {
        "PG&E": {"electricity": "E-TOU-D", "gas": "G-1"},
        "SCE": {"electricity": "TOU-D-4-9PM", "gas": "GR"},
        "SDG&E": {"electricity": "TOU-DR1", "gas": "GR"},
    }

    print(f"\nRunning cost analysis for scenario: {scenario}")
    print(f"Housing type: {housing_type}")
    all_counties = norcal_counties + central_counties + socal_counties
    print(f"Counties: {len(all_counties)} total counties")
    print("-" * 60)

    cost_service = CostService(
        scenario,
        housing_type,
        counties=all_counties,
        rate_plans=rate_plans,
        input_dir=input_dir,
        output_dir=output_dir,
    )
    cost_service.run()

    print("\nCost analysis completed successfully!")
    print(f"Results saved to: {output_dir}")

