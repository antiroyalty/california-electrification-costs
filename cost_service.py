import sys
import argparse
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
# import step9_solar_storage_custom_dispatch as RunSamModelForSolarStorage     # Pvsamv1 PV + custom dispatch
import step9_my_own_solar_storage as RunSamModelForSolarStorage             # DIY PV + custom dispatch
import step10_get_loads_for_rates as GetLoadsForRates
import step11_evaluate_gas_rates as EvaluateGasRates
import step12_evaluate_electricity_rates as EvaluateElectricityRates
import step13_combine_total_annual_costs as CombineTotalAnnualCosts
import step14_build_capital_costs_lifetimes_incentives as BuildCapitalCostsLifetimesIncentives
import step15_payback_periods as PaybackPeriods
import step16_display_key_metrics_maps as DisplayKeyMetricsMaps
from helpers.main_helpers import norcal_counties, socal_counties, central_counties

# Comparison + EAC helpers (Steps 18–21)
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

import os
import subprocess
import pandas as pd

# Introspect dispatch/sizing choices used in Step 9
try:
    import step9_my_own_solar_storage as Step9
except Exception:
    Step9 = None

class CostService:

    def __init__(self, scenario, housing_type, counties, rate_plans, input_dir, output_dir):
        self.scenario = scenario
        self.housing_type = housing_type
        self.counties = counties
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.desired_rate_plans = rate_plans

    def log_step(self, step):
        print("-" * 15, f" Step {step} ", "-" * 15)

    def run(self):
        self.log_step(1)
        IdentifySuitableBuildings.process(scenario, self.housing_type, output_base_dir="data", target_counties=self.counties, force_recompute=False)

        self.log_step(2)
        PullBuildings.process(scenario, self.housing_type, self.counties, output_base_dir="data", download_new_files=False) # output directory should just be 'data', not 'loadprofiles'
    
        self.log_step(3)
        BuildElectricityLoadProfiles.process(scenario, SCENARIOS[scenario], self.housing_type, self.counties, "data", "data/loadprofiles", force_recompute=False)

        self.log_step(4)
        BuildGasLoadProfiles.process("data", "data/loadprofiles", scenario, SCENARIOS, self.housing_type, self.counties, force_recompute=False)

        self.log_step(5)
        ConvertGasToElectric.process("data/loadprofiles", "data/loadprofiles", self.counties, scenario, [self.housing_type], force_recompute=False)

        self.log_step(6)
        # Build vehicle load profiles (EV charging and/or ICE fuel consumption) based on scenario
        BuildElectricVehicleLoadProfiles.process("data", "data/loadprofiles", scenario, SCENARIOS[scenario], [self.housing_type], self.counties, force_recompute=False)

        self.log_step(7)
        # Add EVs here so they get used in SAM model deployment
        CombineRealAndSimulatedProfiles.process("data/loadprofiles", "data/loadprofiles", scenario, [self.housing_type], self.counties, force_recompute=False)
    
        self.log_step(8)
        WeatherFiles.process("data/loadprofiles", "data/loadprofiles", scenario, [self.housing_type], 2018, self.counties)

        self.log_step(9)
        RunSamModelForSolarStorage.process("data/loadprofiles", "data/loadprofiles", scenario, self.housing_type, self.counties, force_recompute=True)

        self.log_step(10)
        GetLoadsForRates.process("data/loadprofiles", "data/loadprofiles", scenario, [self.housing_type], self.counties)

        self.log_step(11)
        EvaluateGasRates.process("data/loadprofiles", "data/loadprofiles", scenario, [self.housing_type], self.counties)

        self.log_step(12)
        EvaluateElectricityRates.process("data/loadprofiles", "data/loadprofiles", scenario, self.housing_type, self.counties)

        self.log_step(13)
        CombineTotalAnnualCosts.process("data/loadprofiles", "data/loadprofiles", scenario, [self.housing_type], self.counties)

        self.log_step(14)
        BuildCapitalCostsLifetimesIncentives.process("data/loadprofiles", "data/loadprofiles", scenario, self.housing_type, self.counties)
        
        self.log_step(15)
        PaybackPeriods.process("data/loadprofiles", scenario, self.housing_type, self.counties)
        
        self.log_step(16)
        # DisplayKeyMetricsMaps.process("data/loadprofiles", "data/loadprofiles", scenario, self.housing_type, self.counties, self.desired_rate_plans)

        # Additional consolidated comparisons and EAC summaries
        self._run_eac_and_comparisons()

    def _git_short_sha(self) -> str:
        try:
            sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL).decode().strip()
            return sha or "nogit"
        except Exception:
            return "nogit"

    def _scenario_list_for_comparisons(self):
        """Return an ordered scenario list for cross-scenario plots.

        Includes a broad mix so EAC bars communicate tradeoffs clearly if data exist.
        """
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
        # Keep only those present in SCENARIOS to avoid typos
        return [s for s in preferred if s in SCENARIOS]

    def _summarize_dispatch_and_sizing(self):
        try:
            if Step9 is None:
                return ""
            mode = "dynamic PV-only" if getattr(Step9, "USE_DYNAMIC_DISPATCH", False) else "classic 4–9pm"
            sizing = "EAC-optimal per county" if getattr(Step9, "USE_EAC_OPTIMAL_SIZING", False) else f"fraction of annual-match (PV_SIZE_FRACTION={getattr(Step9, 'PV_SIZE_FRACTION', 'n/a')})"
            batt = getattr(Step9, "BATTERY_CAPACITY_KWH", None)
            batt_str = f", default battery ≈{batt} kWh" if batt else ""
            # Electricity plan preference summary
            plans = sorted({v.get('electricity') for v in self.desired_rate_plans.values() if isinstance(v, dict) and v.get('electricity')})
            plan_str = f"; Electricity plan preference: {', '.join(plans)}" if plans else ""
            return f"Dispatch: {mode}; Sizing: {sizing}{batt_str}{plan_str}; Billing variant: NEM3 for with-solar"
        except Exception:
            return ""

    def _run_eac_and_comparisons(self):
        """Wire Steps 18–21 style comparisons to run end-to-end and print concise insights.

        - Step 18: Cross-scenario EAC stacked bars (with PV/storage)
        - Step 19: Focused two-scenario comparison (ICE vs EV baseline)
        - Step 20: EAC without PV/storage for context
        - Step 21: With-vs-Without PV/storage for the selected scenario
        """
        base_input_dir = self.output_dir
        output_dir = os.path.join("analysis_results")
        os.makedirs(output_dir, exist_ok=True)
        sha = self._git_short_sha()

        # Print dispatch/sizing assumptions once for clarity
        ds = self._summarize_dispatch_and_sizing()
        if ds:
            print(f"\nAssumptions — {ds}")

        # ----- Step 18: Cross-scenario EAC (with PV/storage) -----
        self.log_step(18)
        scenarios_18 = self._scenario_list_for_comparisons()
        try:
            eac_df = collect_eac_components(
                base_input_dir,
                self.housing_type,
                scenarios_18,
                self.counties,
                incentive="full_incentives",
                agg="mean",
                electricity_plan_preference=list({v.get('electricity') for v in self.desired_rate_plans.values() if isinstance(v, dict) and v.get('electricity')}),
                electricity_variant="nem3",
            )
            if not eac_df.empty:
                # Compute totals for ranking
                comp_cols = [
                    "capex_pv",
                    "capex_storage",
                    "capex_electric",
                    "capex_gas",
                    "vehicle_om",
                ]
                if "annual_bill_electric" in eac_df.columns and "annual_bill_gas" in eac_df.columns:
                    bill_col = eac_df["annual_bill_electric"].fillna(0) + eac_df["annual_bill_gas"].fillna(0)
                else:
                    bill_col = eac_df.get("annual_bill_with_solar", pd.Series([0] * len(eac_df)))
                eac_df["total_eac"] = eac_df[comp_cols].sum(axis=1) + bill_col

                csv18 = os.path.join(output_dir, f"step18_eac_summary_g{sha}.csv")
                eac_df.to_csv(csv18, index=False)
                fig18 = plot_eac_stacked_bar(eac_df, scenario_order=scenarios_18)
                png18 = os.path.join(output_dir, f"step18_eac_stacked_bar_g{sha}.png")
                fig18.savefig(png18, dpi=150, bbox_inches="tight")

                # Console: top scenarios by lowest EAC
                top = eac_df.sort_values("total_eac").head(5)[["scenario", "total_eac"]]
                print("Cross-scenario EAC (with PV) — lowest totals:")
                for _, r in top.iterrows():
                    print(f"  {r['scenario']}: ${r['total_eac']:.0f}/yr")
                print(f"Saved EAC stacked bar: {os.path.abspath(png18)}")

                # Save per-county tidy EAC tables for deeper analysis (NEM3 and retail).
                plan_pref = list({v.get('electricity') for v in self.desired_rate_plans.values() if isinstance(v, dict) and v.get('electricity')})
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
            else:
                print("Cross-scenario EAC: no data available (skipping plot)")
        except Exception as err:
            print(f"Cross-scenario EAC failed: {err}")

        # ----- Step 19: Two-scenario EAC comparison (ICE vs EV) -----
        self.log_step(19)
        try:
            pair = [s for s in ["baseline_ice_car", "baseline_ev_car"] if s in SCENARIOS]
            if len(pair) == 2:
                eac19 = collect_eac_components(
                    base_input_dir,
                    self.housing_type,
                    pair,
                    self.counties,
                    incentive="full_incentives",
                    agg="mean",
                    electricity_plan_preference=list({v.get('electricity') for v in self.desired_rate_plans.values() if isinstance(v, dict) and v.get('electricity')}),
                    electricity_variant="nem3",
                )
                if not eac19.empty:
                    # Compute totals and difference (EV - ICE)
                    if "annual_bill_electric" in eac19.columns and "annual_bill_gas" in eac19.columns:
                        eac19["total_eac"] = (
                            eac19[["capex_pv", "capex_storage", "capex_electric", "capex_gas", "vehicle_om"]].sum(axis=1)
                            + eac19["annual_bill_electric"].fillna(0)
                            + eac19["annual_bill_gas"].fillna(0)
                        )
                    else:
                        eac19["total_eac"] = (
                            eac19[["capex_pv", "capex_storage", "capex_electric", "capex_gas", "vehicle_om", "annual_bill_with_solar"]].sum(axis=1)
                        )
                    fig19 = plot_eac_stacked_bar(eac19, scenario_order=pair, title=f"All-in Annualized Cost — {pair[0]} vs {pair[1]}")
                    png19 = os.path.join(output_dir, f"step19_eac_stacked_bar_{pair[0]}_vs_{pair[1]}_g{sha}.png")
                    fig19.savefig(png19, dpi=150, bbox_inches="tight")

                    try:
                        ice_val = float(eac19[eac19["scenario"] == pair[0]]["total_eac"].values[0])
                        ev_val = float(eac19[eac19["scenario"] == pair[1]]["total_eac"].values[0])
                        delta = ev_val - ice_val
                        sign = "higher" if delta > 0 else "lower"
                        print(f"EV vs ICE annualized cost: {pair[1]} is ${abs(delta):.0f}/yr {sign} than {pair[0]}")
                    except Exception:
                        pass
                    print(f"Saved EV vs ICE EAC: {os.path.abspath(png19)}")

                    # Per-county EV vs ICE deltas (NEM3 variant)
                    plan_pref = list({v.get('electricity') for v in self.desired_rate_plans.values() if isinstance(v, dict) and v.get('electricity')})
                    by_cty = collect_eac_components_by_county(
                        base_input_dir,
                        self.housing_type,
                        pair,
                        self.counties,
                        incentive="full_incentives",
                        electricity_plan_preference=plan_pref,
                        electricity_variant="nem3",
                    )
                    if not by_cty.empty:
                        by_cty = by_cty.copy()
                        by_cty["total_eac"] = (
                            by_cty[["capex_pv","capex_storage","capex_electric","capex_gas","vehicle_om"]].sum(axis=1)
                            + by_cty["annual_bill_electric"].fillna(0) + by_cty["annual_bill_gas"].fillna(0)
                        )
                        a = by_cty[by_cty["scenario"] == pair[0]][["county_slug","total_eac"]].rename(columns={"total_eac": f"{pair[0]}_total"})
                        b = by_cty[by_cty["scenario"] == pair[1]][["county_slug","total_eac"]].rename(columns={"total_eac": f"{pair[1]}_total"})
                        m = a.merge(b, on="county_slug", how="inner")
                        m["delta_ev_minus_ice"] = m[f"{pair[1]}_total"] - m[f"{pair[0]}_total"]
                        m.to_csv(os.path.join(output_dir, f"step19_ev_vs_ice_by_county_g{sha}.csv"), index=False)
                else:
                    print("Two-scenario EAC: no data available (skipping)")
            else:
                print("Two-scenario EAC: scenarios not defined; skipping")
        except Exception as err:
            print(f"Two-scenario EAC failed: {err}")

        # ----- Step 20: No-solar EAC for context (current scenario) -----
        self.log_step(20)
        try:
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
            if not eac20.empty:
                csv20 = os.path.join(output_dir, f"step20_eac_no_pv_summary_g{sha}.csv")
                eac20.to_csv(csv20, index=False)
                fig20 = plot_eac_no_pv_stacked_bar(eac20, scenario_order=scen20, title=f"All-in Annualized Cost (No Solar + Storage) — {self.scenario}")
                png20 = os.path.join(output_dir, f"step20_eac_no_pv_stacked_bar_g{sha}.png")
                fig20.savefig(png20, dpi=150, bbox_inches="tight")
                print(f"Saved no-PV EAC: {os.path.abspath(png20)}")
            else:
                print("No-PV EAC: no data available (skipping)")
        except Exception as err:
            print(f"No-PV EAC failed: {err}")

        # ----- Step 21: With vs Without PV for selected scenario -----
        self.log_step(21)
        try:
            with_df = collect_eac_components(
                base_input_dir,
                self.housing_type,
                [self.scenario],
                self.counties,
                incentive="full_incentives",
                agg="mean",
                electricity_plan_preference=list({v.get('electricity') for v in self.desired_rate_plans.values() if isinstance(v, dict) and v.get('electricity')}),
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
            if not with_df.empty and not no_df.empty:
                # Harmonize into a single tidy frame with variant labels
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

                # Save merged CSV and plot
                csv21 = os.path.join(output_dir, f"step21_eac_with_vs_without_g{sha}.csv")
                merged.to_csv(csv21, index=False)
                fig21 = plot_grouped_eac(merged, scenario_order=[self.scenario], county_label="All Counties")
                png21 = os.path.join(output_dir, f"step21_eac_with_vs_without_g{sha}.png")
                fig21.savefig(png21, dpi=150, bbox_inches="tight")

                # Console: is PV+storage worth it?
                def total_from(row: pd.Series) -> float:
                    return float(
                        row[["capex_pv", "capex_storage", "capex_electric", "capex_gas", "vehicle_om"]].sum()
                        + float(row.get("annual_bill_electric", 0.0))
                        + float(row.get("annual_bill_gas", 0.0))
                    )

                t_no = total_from(merged[(merged["scenario"] == self.scenario) & (merged["variant"] == "no_pv")].iloc[0])
                t_yes = total_from(merged[(merged["scenario"] == self.scenario) & (merged["variant"] == "with_pv")].iloc[0])
                delta = t_yes - t_no
                pct = (delta / t_no) * 100 if t_no else 0.0
                verdict = "LOWER" if delta < 0 else "HIGHER"
                print(f"With PV+storage total EAC is ${abs(delta):.0f}/yr ({abs(pct):.1f}%) {verdict} than electrification-only for {self.scenario}.")
                print(f"Saved with-vs-without EAC: {os.path.abspath(png21)}")

                # Per-county with-vs-without deltas for this scenario (tidy CSV)
                plan_pref = list({v.get('electricity') for v in self.desired_rate_plans.values() if isinstance(v, dict) and v.get('electricity')})
                with_by_cty = collect_eac_components_by_county(
                    base_input_dir,
                    self.housing_type,
                    [self.scenario],
                    self.counties,
                    incentive="full_incentives",
                    electricity_plan_preference=plan_pref,
                    electricity_variant="nem3",
                )
                no_by_cty = collect_eac_no_pv_by_county(
                    base_input_dir,
                    self.housing_type,
                    [self.scenario],
                    self.counties,
                    incentive="full_incentives",
                    discount_rate=0.07,
                )
                if not with_by_cty.empty and not no_by_cty.empty:
                    # Compute totals and deltas
                    with_by_cty = with_by_cty.copy()
                    with_by_cty["total_eac"] = (
                        with_by_cty[["capex_pv","capex_storage","capex_electric","capex_gas","vehicle_om"]].sum(axis=1)
                        + with_by_cty["annual_bill_electric"].fillna(0) + with_by_cty["annual_bill_gas"].fillna(0)
                    )
                    no_by_cty = no_by_cty.copy()
                    no_by_cty["total_eac_no_pv"] = (
                        no_by_cty[["capex_electric","capex_gas","vehicle_om"]].sum(axis=1)
                        + no_by_cty["annual_bill_electric"].fillna(0) + no_by_cty["annual_bill_gas"].fillna(0)
                    )
                    merged_cty = with_by_cty.merge(no_by_cty[["scenario","county_slug","total_eac_no_pv"]], on=["scenario","county_slug"], how="inner")
                    merged_cty["delta_with_minus_without"] = merged_cty["total_eac"] - merged_cty["total_eac_no_pv"]
                    merged_cty["delta_pct"] = (merged_cty["delta_with_minus_without"] / merged_cty["total_eac_no_pv"]).replace([pd.NA, float('inf'), float('-inf')], 0.0) * 100.0
                    merged_cty.to_csv(os.path.join(output_dir, f"step21_with_vs_without_by_county_g{sha}.csv"), index=False)
            else:
                print("With-vs-Without EAC: insufficient data (skipping)")
        except Exception as err:
            print(f"With-vs-Without EAC failed: {err}")

def parse_arguments():
    """
    Parse command-line arguments for the cost service.
    """
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
  python3 cost_service.py baseline"""
    )
    
    parser.add_argument(
        "scenario",
        help="Electrification scenario to analyze"
    )
    
    return parser.parse_args()


if __name__ == '__main__':
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
            "PG&E": {
                "electricity": "E-TOU-D",
                "gas": "G-1"
            },
            "SCE": {
                "electricity": "TOU-D-4-9PM",
                "gas": "GR"
            },
            "SDG&E": {
                "electricity": "TOU-DR1",
                "gas": "GR"
            }
        }
    
    print(f"\nRunning cost analysis for scenario: {scenario}")
    print(f"Housing type: {housing_type}")
    print(f"Counties: {len(norcal_counties + central_counties + socal_counties)} total counties")
    print("-" * 60)
    alameda_county = ["Alameda County"]

    cost_service = CostService(scenario, housing_type, counties=alameda_county, rate_plans=rate_plans, input_dir=input_dir, output_dir=output_dir)
    cost_service.run()
    
    print("\nCost analysis completed successfully!")
    print(f"Results saved to: {output_dir}")
