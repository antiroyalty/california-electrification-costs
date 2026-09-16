"""Independent four-cell examples and saved-run collection checks."""
import json

import pandas as pd
import pytest

from figure_builder import electrification as comparison
from figure_builder.datasets import EAC_COMPONENT_COLUMNS
from figure_builder.dispatch import HOUSING_TYPE, LOAD_COL


def _cost_example(county="alameda", totals=(1000, 900, 1050, 850)):
    utility = comparison.resolve_county_service_assignment(county).utility.value
    rows = []
    for (case, (scenario, with_solar)), total in zip(comparison.CASES.items(), totals):
        electric = case.startswith("electric_")
        row = dict.fromkeys(EAC_COMPONENT_COLUMNS, 0.0)
        row.update(
            case=case, scenario=scenario, county_slug=county, utility=utility,
            electricity_column=comparison.electricity_column(utility, with_solar),
            capex_electric=100 if electric else 0,
            capex_gas=0 if electric else 100,
            annual_bill_gas=0 if electric else 50,
            vehicle_om=-10 if electric else 20,
            capex_pv=30 if with_solar else 0,
            solar_kw=1.5 if with_solar else 0, battery_kwh=0,
            solver_cost_gap_usd_per_year=(0.3 if electric else 0.2) if with_solar else 0,
            reporting_cost_difference_usd_per_year=(
                (0.1 if electric else -0.05) if with_solar else 0
            ),
        )
        row["annual_bill_electric"] = total - sum(row[c] for c in EAC_COMPONENT_COLUMNS)
        rows.append(row)
    return pd.DataFrame(rows)


def test_package_effect_separates_electrification_and_adoption_savings():
    # Alameda: electrification alone costs $50 more, but increases adoption
    # savings from $100 to $200. The optimized electric package saves $50.
    # LA: electrification saves money, yet reduces adoption savings by $50.
    costs = pd.concat([_cost_example(), _cost_example("los-angeles", (1000, 900, 800, 750))])
    summary = comparison.summarize_electrification_costs(costs).set_index("county_slug")
    expected = {
        "alameda": (-50, 50, 100, 200, 100),
        "los-angeles": (200, 150, 100, 50, -50),
    }
    columns = ["electrification_savings_no_solar_usd_per_year",
               "electrification_savings_optimized_usd_per_year",
               "gas_adoption_savings_usd_per_year",
               "electric_adoption_savings_usd_per_year", "package_effect_usd_per_year"]
    for county, values in expected.items():
        assert summary.loc[county, columns].tolist() == pytest.approx(values)
        row = summary.loc[county]
        assert row.electrification_savings_optimized_usd_per_year == pytest.approx(
            row.electrification_savings_no_solar_usd_per_year + row.package_effect_usd_per_year
        )
        assert row.comparison_numerical_bound_usd_per_year == pytest.approx(0.6501)


@pytest.mark.parametrize("totals,expected", [
    ((1000, 900, 800, 700), 0),  # Lower total electric cost does not imply synergy.
    ((1000, 1100, 800, 900), 0),  # Adoption can lose money when the plan changes.
    ((0, 0, 0, 0), 0),  # Dollar comparisons do not require a positive denominator.
])
def test_zero_interaction_and_unfavorable_adoption_remain_valid(totals, expected):
    result = comparison.summarize_electrification_costs(_cost_example(totals=totals))
    assert result.loc[0, "package_effect_usd_per_year"] == expected


def test_adoption_figure_uses_paired_differences_and_respects_numerical_bounds():
    from figure_builder.charts import plot_matched_adoption_savings
    import matplotlib.pyplot as plt

    costs = pd.concat([
        _cost_example(),
        _cost_example("los-angeles", (1000, 900, 800, 750)),
        _cost_example("san-diego", (1000, 900, 1000, 899.8)),
        _cost_example("marin", (1000, 1100, 1000, 1050)),
    ])
    fig, meta = plot_matched_adoption_savings(costs)
    try:
        assert meta["county_count"] == 4
        assert meta["higher_adoption_savings_count"] == 2
        assert meta["lower_adoption_savings_count"] == 1
        assert meta["unresolved_sign_count"] == 1
        assert meta["median_package_effect_usd_per_year"] == pytest.approx(25.1)
        # The median interaction must not be replaced by a difference of medians.
        assert meta["median_electric_adoption_savings_usd_per_year"] == pytest.approx(75.1)
        assert meta["median_gas_adoption_savings_usd_per_year"] == 100
        assert meta["maximum_comparison_numerical_bound_usd_per_year"] == pytest.approx(0.6501)
        plotted = [tuple(point) for container in fig.axes[0].containers
                   for point in zip(*container.lines[0].get_data())]
        expected = [(-100, -50), (100, 50), (100, 100.2), (100, 200)]
        assert len(plotted) == len(expected)
        for actual, point in zip(sorted(plotted), expected):
            assert actual == pytest.approx(point)
        assert fig.axes[0].get_xlim()[0] < -100
        caption = "\n".join(text.get_text() for text in fig.texts)
        assert "rate-plan change" in caption
        assert "modeling uncertainty" in caption
    finally:
        plt.close(fig)


def test_adoption_figure_rejects_an_incomplete_county():
    from figure_builder.charts import plot_matched_adoption_savings

    with pytest.raises(ValueError, match="four unique cases"):
        plot_matched_adoption_savings(_cost_example().iloc[:-1])


@pytest.mark.parametrize("defect,message", [
    ("missing_case", "four unique cases"),
    ("extra_county", "four unique cases"),
    ("duplicate", "four unique cases"),
    ("fixed_gas", "requires scenario"),
    ("wrong_plan", "utility or electricity plan"),
    ("wrong_utility", "utility or electricity plan"),
    ("free_missing_cost", "must be finite"),
    ("nonfinite_gap", "must be finite"),
    ("changed_appliance", "Non-solar household costs"),
    ("changed_gas", "Non-solar household costs"),
    ("no_solar_capacity", "No-solar cases"),
    ("negative_battery", "cannot be negative"),
    ("stale_total", "totals do not reconcile"),
])
def test_four_case_validator_rejects_invalid_comparisons(defect, message):
    costs = _cost_example()
    if defect == "missing_case":
        costs = costs.iloc[1:]
    elif defect == "extra_county":
        costs = pd.concat([costs, _cost_example("los-angeles")])
    elif defect == "duplicate":
        costs = pd.concat([costs, costs.iloc[[0]]])
    elif defect == "stale_total":
        costs["total_eac"] = costs[EAC_COMPONENT_COLUMNS].sum(axis=1)
        costs.loc[0, "total_eac"] += 1
    else:
        row, column, value = {
            "fixed_gas": (1, "scenario", "baseline_ice_car"),
            "wrong_plan": (0, "electricity_column", "electricity.PG&E.E-TOU-C"),
            "wrong_utility": (0, "utility", "SCE"),
            "free_missing_cost": (0, "capex_gas", float("nan")),
            "nonfinite_gap": (1, "solver_cost_gap_usd_per_year", float("inf")),
            "changed_appliance": (1, "capex_gas", 101),
            "changed_gas": (1, "annual_bill_gas", 51),
            "no_solar_capacity": (0, "solar_kw", 1),
            "negative_battery": (1, "battery_kwh", -1),
        }[defect]
        costs.loc[row, column] = value
    with pytest.raises(ValueError, match=message):
        comparison.validate_electrification_costs(costs, {"alameda"})


def _saved_runs(tmp_path, counties=("alameda", "los-angeles", "san-diego")):
    base = tmp_path / "loadprofiles"
    completion = tmp_path / "completion"
    timestamps = {
        s: f"20260915_{hour}" for s, hour in zip(comparison.HOUSEHOLDS.values(), (10, 11))
    }
    for household, scenario in comparison.HOUSEHOLDS.items():
        electric = household == "electric"
        ledger, summaries, designs = [], [], []
        for county in counties:
            utility = comparison.resolve_county_service_assignment(county).utility.value
            directory = base / scenario / HOUSING_TYPE / county
            directory.mkdir(parents=True)
            (directory / f"weather_TMY_{county}.csv").write_text(
                f"shared weather fixture: {county}\n"
            )
            pd.DataFrame({LOAD_COL: [2 if electric else 1] * 8760}).to_csv(
                directory / f"combined_profiles_{scenario}_{county}.csv", index=False,
            )
            marker_dir = completion / scenario
            marker_dir.mkdir(exist_ok=True, parents=True)
            (marker_dir / f"{county}_diagnostics_gabc1234.html").write_text("completed fixture")
            for kind, cost, operating in (
                ("heating", 1500 if electric else 600, 0),
                ("vehicle_charging" if electric else "vehicle_fuel",
                 18000 if electric else 12000, -60 if electric else 120),
            ):
                ledger.append({
                    "county_slug": county, "incentive_scenario": "full_incentives",
                    "appliance_category": "electric" if electric else "gas",
                    "appliance_type": kind, "net_cost": cost, "base_cost": cost,
                    "lifetime_years": 15, "annual_operating_cost": operating,
                })
            summaries.append({"county_slug": county, "pv_capex": 3300,
                              "storage_capex": 0, "pv_incentives_full": 0,
                              "storage_incentives_full": 0})
            design = dict.fromkeys(comparison.MATCHED_SETTINGS, "fixture")
            design.update({
                "County": county, "Utility": utility,
                "Import Tariff Plan": comparison.required_nbt_import_plan(utility),
                "NBT Billing Year": 2026, "NBT Interconnection Vintage": 2026,
                "Battery Capacity Upper Bound (kWh)": 40,
                "Allow Grid Charging": False, "Allow Battery Export": True,
                "Solver Cost Tolerance (USD/year)": 1,
                "Solver Cost Gap (USD/year)": 0.25,
                "Solar Capacity (kW)": 1, "Battery Capacity (kWh)": 0,
                "Coopt Total Cost": 883.1747,
            })
            designs.append(design)
            retail = comparison.electricity_column(utility, False)
            nbt = comparison.electricity_column(utility, True)
            for fuel, rows in (
                ("electricity", [
                    {"scenario": scenario, retail: 1200, nbt: float("nan")},
                    {"scenario": scenario + ".solarstorage", retail: 800, nbt: 600},
                ]),
                ("gas", [
                    {"scenario": scenario, "gas.default": 0 if electric else 300},
                    {"scenario": scenario + ".solarstorage", "gas.default": 0 if electric else 300},
                ]),
            ):
                output = directory / "results" / fuel
                output.mkdir(parents=True)
                name = f"RESULTS_{fuel}_annual_costs_{county}_{timestamps[scenario]}.csv"
                pd.DataFrame(rows).to_csv(output / name, index=False)
                # A newer file must not displace the requested completed run.
                pd.DataFrame(rows).assign(unrelated=9999).to_csv(
                    output / f"RESULTS_{fuel}_annual_costs_{county}_20260916_12.csv", index=False,
                )
        capital = base / "capital_costs"
        capital.mkdir(exist_ok=True)
        suffix = f"{scenario}_single_family_detached.csv"
        pd.DataFrame(ledger).to_csv(capital / f"capital_costs_{suffix}", index=False)
        pd.DataFrame(summaries).to_csv(
            capital / f"capital_costs_summary_with_pv_{suffix}", index=False
        )
        assets = base / scenario / HOUSING_TYPE / "CAPITAL_COSTS"
        assets.mkdir()
        pd.DataFrame(designs).to_csv(assets / "electrified_assets.csv", index=False)
    return dict(model_run_sha="abc1234", run_timestamps=timestamps, base_input_dir=base,
                completion_dir=completion, source=tmp_path / "matched.csv", counties=set(counties))


def test_renders_verified_source_with_image_pdf_and_receipt(tmp_path):
    from figure_builder.electrification_figure import render_adoption_figure

    source = comparison.build_electrification_source(**_saved_runs(tmp_path))
    prefix = tmp_path / "figures" / "adoption"
    receipt = render_adoption_figure(source, prefix)
    assert prefix.with_suffix(".png").read_bytes().startswith(b"\x89PNG")
    assert prefix.with_suffix(".pdf").read_bytes().startswith(b"%PDF")
    assert json.loads(prefix.with_suffix(".json").read_text()) == receipt
    assert receipt["source"] == comparison.file_identity(source)
    assert receipt["statistics"]["county_count"] == 3
    assert receipt["statistics"]["unresolved_sign_count"] == 3
    for suffix, artifact in zip((".png", ".pdf"), receipt["artifacts"]):
        assert comparison.file_identity(prefix.with_suffix(suffix)) == artifact
    with pytest.raises(ValueError, match="cannot replace"):
        render_adoption_figure(source, source.with_suffix(".manifest"))
    source.write_text(source.read_text() + "\n")
    with pytest.raises(ValueError, match="fingerprint"):
        render_adoption_figure(source, prefix)


def test_builds_four_cells_from_two_completed_runs_and_records_exact_sources(tmp_path):
    args = _saved_runs(tmp_path)
    source = comparison.build_electrification_source(**args)
    costs = comparison.load_electrification_costs(source)
    manifest = json.loads(source.with_suffix(".manifest.json").read_text())
    assert len(costs) == 12
    assert set(costs.case) == set(comparison.CASES)
    assert manifest["scenario_run_timestamps"] == args["run_timestamps"]
    assert manifest["model_git_sha"] == "abc1234"
    assert set(manifest["matched_settings_by_county"]) == args["counties"]
    paths = [entry["path"] for entry in manifest["source_files"]]
    assert not any("20260916_12" in p for p in paths)
    assert sum("diagnostics_gabc1234" in p for p in paths) == 6
    assert sum("capital_costs_summary_with_pv" in p for p in paths) == 2
    assert all(len(entry["sha256"]) == 64 for entry in manifest["source_files"])
    for case, (_, with_solar) in comparison.CASES.items():
        bills = costs.loc[costs.case == case, "annual_bill_electric"]
        assert (bills == (600 if with_solar else 1200)).all()
    saved = pd.read_csv(source.with_suffix(".comparisons.csv"))
    pd.testing.assert_frame_equal(saved, comparison.summarize_electrification_costs(costs))


@pytest.mark.parametrize("defect,message", [
    ("missing_completion", "file not found"),
    ("wrong_timestamp", "timestamp"),
    ("wrong_scenario", "exactly both optimized"),
    ("fixed_baseline", "exactly both optimized"),
    ("partial_year", "8760-hour"),
    ("weather", "Weather inputs differ"),
    ("settings", "Optimization settings differ"),
    ("wrong_plan", "Exact bill plan"),
    ("solver_gap", "Invalid solver cost gap"),
])
def test_source_builder_rejects_unmatched_or_incomplete_runs(tmp_path, defect, message):
    args = _saved_runs(tmp_path, ("alameda",))
    scenario = comparison.HOUSEHOLDS["gas"]
    directory = args["base_input_dir"] / scenario / HOUSING_TYPE / "alameda"
    if defect == "missing_completion":
        (args["completion_dir"] / scenario / "alameda_diagnostics_gabc1234.html").unlink()
    elif defect == "wrong_timestamp":
        args["run_timestamps"][scenario] = "20260917_10"
    elif defect in {"wrong_scenario", "fixed_baseline"}:
        wrong = "baseline_ice_car" if defect == "fixed_baseline" else "baseline_coopt"
        args["run_timestamps"][wrong] = args["run_timestamps"].pop(scenario)
    elif defect == "partial_year":
        pd.DataFrame({LOAD_COL: [1, 2]}).to_csv(
            directory / f"combined_profiles_{scenario}_alameda.csv", index=False
        )
    elif defect == "weather":
        (directory / "weather_TMY_alameda.csv").write_text("different weather")
    elif defect == "wrong_plan":
        path = (directory / "results" / "electricity"
                / "RESULTS_electricity_annual_costs_alameda_20260915_10.csv")
        frame = pd.read_csv(path).rename(
            columns={"electricity.PG&E.E-TOU-D": "electricity.PG&E.E-TOU-C"}
        )
        frame.to_csv(path, index=False)
    else:
        path = directory.parent / "CAPITAL_COSTS" / "electrified_assets.csv"
        frame = pd.read_csv(path)
        column = ("Solver Cost Gap (USD/year)" if defect == "solver_gap"
                  else "Battery Capacity Upper Bound (kWh)")
        frame.loc[0, column] = 2 if defect == "solver_gap" else 20
        frame.to_csv(path, index=False)
    with pytest.raises((ValueError, FileNotFoundError), match=message):
        comparison.build_electrification_source(**args)
    assert not args["source"].exists()


def test_load_rejects_replaced_source_csv(tmp_path):
    path = comparison.build_electrification_source(**_saved_runs(tmp_path, ("alameda",)))
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="fingerprint"):
        comparison.load_electrification_costs(path)


def test_collection_rejects_inputs_changed_during_the_read(tmp_path, monkeypatch):
    args = _saved_runs(tmp_path, ("alameda",))
    collect = comparison.collect_eac_components_by_county
    weather = (args["base_input_dir"] / comparison.HOUSEHOLDS["gas"] / HOUSING_TYPE
               / "alameda" / "weather_TMY_alameda.csv")

    def collect_then_change_input(*positional, **kwargs):
        result = collect(*positional, **kwargs)
        weather.write_text("changed after initial read")
        return result

    monkeypatch.setattr(comparison, "collect_eac_components_by_county", collect_then_change_input)
    with pytest.raises(ValueError, match="changed during collection"):
        comparison.build_electrification_source(**args)
    assert not args["source"].exists()


def test_comparison_output_cannot_overwrite_a_capital_ledger(tmp_path):
    args = _saved_runs(tmp_path, ("alameda",))
    path = (args["base_input_dir"] / "capital_costs"
            / "capital_costs_baseline_ice_car_coopt_single_family_detached.csv")
    original = path.read_bytes()
    args["source"] = path
    with pytest.raises(ValueError, match="cannot replace a source input"):
        comparison.build_electrification_source(**args)
    assert path.read_bytes() == original


def test_loaded_source_requires_valid_run_identity(tmp_path):
    path = comparison.build_electrification_source(**_saved_runs(tmp_path, ("alameda",)))
    manifest_path = path.with_suffix(".manifest.json")
    manifest = json.loads(manifest_path.read_text())
    manifest["model_git_sha"] = "latest"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="model_run_sha"):
        comparison.load_electrification_costs(path)
