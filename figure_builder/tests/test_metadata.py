import json
from datetime import datetime, timezone

import pytest

from figure_builder.datasets import CLAIMS_EAC_SCENARIOS, claims_eac_manifest_path
from figure_builder.dispatch import CLAIM1_COUNTIES
from figure_builder.metadata import (
    build_run_metadata,
    capital_cost_metadata,
    file_identity,
    optimization_metadata,
    tariff_metadata,
    write_run_metadata,
)


def test_file_identity_detects_content_changes(tmp_path):
    source = tmp_path / "source.csv"
    source.write_text("first\n", encoding="utf-8")
    first = file_identity(source)
    source.write_text("second\n", encoding="utf-8")
    second = file_identity(source)

    assert first["sha256"] != second["sha256"]
    assert first["size_bytes"] == 6
    assert second["size_bytes"] == 7


def test_capital_cost_metadata_records_both_exact_regime_prices_and_sources():
    metadata = capital_cost_metadata()
    regimes = {row["regime"]: row for row in metadata["policy_regimes"]}

    assert metadata["gross_cost_basis"]["pv"]["value_usd_per_kw"] == 3300.0
    assert metadata["gross_cost_basis"]["pv"]["basis_year"] == 2023
    assert metadata["gross_cost_basis"]["battery"]["value_usd_per_kwh"] == 1460.64
    assert metadata["gross_cost_basis"]["battery"]["basis_year"] == 2023
    assert regimes["post_itc_2026"]["federal_itc_fraction"] == 0.0
    assert regimes["post_itc_2026"]["battery_net_usd_per_kwh"] == 1460.64
    assert regimes["itc_2025"]["federal_itc_fraction"] == 0.30
    assert regimes["itc_2025"]["battery_net_usd_per_kwh"] == 1022.448
    for row in regimes.values():
        exact = row["exact_battery_sweep_observation_usd_per_kwh"]
        assert row["battery_sweep_points_usd_per_kwh"].count(exact) == 1


def test_tariff_metadata_records_every_source_used_by_the_sweep():
    metadata = tariff_metadata()
    utilities = {row["utility"]: row for row in metadata["utilities"]}
    comparison = metadata["comparison"]
    nem2_utilities = {
        row["utility"]: row
        for row in comparison["nem2_scenario"]["utilities"]
    }

    assert metadata["scenario"] == {
        "billing_year": 2026,
        "nbt_vintage": 2026,
        "service_type": "bundled",
        "customer_segment": "standard_non_equity",
        "tariff_snapshot_date": "2026-08-09",
    }
    assert utilities["PG&E"]["import"]["source_id"] == "pge_e_elec_2026-06-01"
    assert utilities["PG&E"]["export"]["source_ids"] == ["pge_nbt2026"]
    assert utilities["PG&E"]["acc_plus"]["source_id"] == "pge_advice_7174_e"
    assert utilities["SCE"]["import"]["source_id"] == "sce_tou_d_prime_2026-06-01"
    assert utilities["SCE"]["export"]["source_ids"] == ["sce_nbt2026"]
    assert utilities["SCE"]["acc_plus"]["source_id"] == "sce_schedule_nbt"
    assert utilities["SDG&E"]["import"]["source_id"] == "sdge_ev_tou_5_2026-08-01"
    assert utilities["SDG&E"]["export"]["source_ids"] == ["sdge_nbt2026"]
    assert utilities["SDG&E"]["acc_plus"]["source_id"] == "cpuc_nbt_policy"
    assert metadata["annual_true_up"]["used_by_sweep"] is False
    assert comparison["nem2_scenario"]["research_label"] == (
        "nem2_at_2026_retail_rates"
    )
    assert comparison["nem2_scenario"]["tariff_snapshot_date"] == (
        "2026-08-09"
    )
    assert len(comparison["policy_cases"]) == 4
    assert "not a historical bill replay" in comparison["research_design"]
    assert nem2_utilities["PG&E"]["settlement"][
        "retail_credit_exclusion_rate_usd_per_kwh"
    ] == pytest.approx(0.01621)
    assert nem2_utilities["SCE"]["settlement"][
        "monthly_net_consumption_rate_usd_per_kwh"
    ] == pytest.approx(0.00619)
    assert nem2_utilities["SDG&E"]["settlement"][
        "nsc_rate_source_id"
    ] == "sdge_monthly_nsc_rates_2026-08-10"
    assert "data/tariffs/nem2_source_manifest.json" in metadata[
        "source_manifests"
    ]
    assert "data/tariffs/true_up_source_manifest.json" in metadata[
        "source_manifests"
    ]


def test_optimization_metadata_matches_declared_coarse_sweep_settings():
    metadata = optimization_metadata(fine=False)

    assert metadata["temporal_resolution"] == {
        "name": "weighted_12x24_monthly_hour",
        "interval_count": 288,
        "soc_cycle": "monthly",
    }
    assert metadata["market_price_observations"] == {
        "name": "full_8760_hour",
        "interval_count": 8760,
        "soc_cycle": "annual",
        "points_per_county_and_case": 1,
        "policy_cases": [
            "nbt_2026__post_itc_2026",
            "nem2_at_2026_retail_rates__post_itc_2026",
            "nem2_at_2026_retail_rates__itc_2025",
        ],
        "excluded_policy_cases": ["nbt_2026__itc_2025"],
        "purpose": (
            "Exact solved observations for declared publication policy "
            "cases. NBT with 2025 ITC capital prices remains an explicitly "
            "labeled 12x24 sensitivity."
        ),
    }
    assert metadata["solver"]["backend"] == "highs"
    assert metadata["solver"]["mip_relative_gap"] == 1e-6
    assert metadata["sizing_domain"]["max_battery_kwh"] == 40.0
    assert metadata["sizing_domain"]["max_pv_to_annual_load_ratio"] == 1.5
    assert metadata["sizing_domain"][
        "max_pv_to_annual_load_ratio_by_export_compensation_regime"
    ] == {
        "nbt_2026": 1.5,
        "nem2_at_2026_retail_rates": 1.0,
    }
    assert metadata["battery_physics"]["round_trip_efficiency"] == 0.96
    assert metadata["battery_physics"]["allow_grid_charging"] is False
    assert metadata["battery_physics"]["allow_battery_export"] is True
    assert metadata["financial_assumptions"]["battery_power_cost_usd_per_kw"] == 0.0
    assert (
        metadata["financial_assumptions"][
            "battery_degradation_cost_usd_per_kwh"
        ]
        == 0.0
    )


def test_build_run_metadata_hashes_inputs_and_deduplicates_artifacts(
    tmp_path,
    monkeypatch,
):
    scenario = "test_scenario"
    housing_type = "single-family-detached"
    for slug, _, _ in CLAIM1_COUNTIES:
        county_dir = tmp_path / scenario / housing_type / slug
        county_dir.mkdir(parents=True)
        (county_dir / f"weather_TMY_{slug}.csv").write_text(
            f"weather,{slug}\n",
            encoding="utf-8",
        )
        (county_dir / f"combined_profiles_{scenario}_{slug}.csv").write_text(
            f"load,{slug}\n",
            encoding="utf-8",
        )
    artifact = tmp_path / "result.csv"
    artifact.write_text("result\n", encoding="utf-8")
    monkeypatch.setattr("figure_builder.metadata.git_short_sha", lambda: "abc1234")

    metadata = build_run_metadata(
        [artifact, artifact],
        fine=False,
        force=True,
        generated_at=datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc),
        scenario=scenario,
        base_input_dir=tmp_path,
    )

    assert metadata["run"]["generated_at_utc"] == "2026-08-17T12:00:00+00:00"
    assert metadata["schema_version"] == 4
    assert metadata["run"]["git_sha"] == "abc1234"
    assert metadata["run"]["force"] is True
    assert metadata["run"]["command_argv"] == [
        "python3",
        "-m",
        "figure_builder",
        "all",
        "--force",
    ]
    assert len(metadata["run"]["counties"]) == 4
    assert len(metadata["inputs"]) == 8
    assert {row["role"] for row in metadata["inputs"]} == {
        "weather_tmy",
        "combined_load_profile",
    }
    assert len(metadata["artifacts"]) == 1
    assert metadata["statewide_claims"] is None
    json.dumps(metadata)


def test_build_run_metadata_hashes_and_identifies_statewide_claims_source(
    tmp_path,
    monkeypatch,
):
    scenario = "test_scenario"
    housing_type = "single-family-detached"
    for slug, _, _ in CLAIM1_COUNTIES:
        county_dir = tmp_path / scenario / housing_type / slug
        county_dir.mkdir(parents=True)
        (county_dir / f"weather_TMY_{slug}.csv").write_text(
            f"weather,{slug}\n",
            encoding="utf-8",
        )
        (county_dir / f"combined_profiles_{scenario}_{slug}.csv").write_text(
            f"load,{slug}\n",
            encoding="utf-8",
        )
    claims_source = tmp_path / "step18_eac.csv"
    claims_source.write_text("scenario,county_slug,total_eac\n", encoding="utf-8")
    claims_eac_manifest_path(claims_source).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "model_git_sha": "abc1234",
                "scenario_run_timestamps": {
                    "baseline_ice_car": "20260817_17",
                    "full_electric_ev": "20260817_17",
                    "full_electric_ev_coopt": "20260817_18",
                },
                "scenario_cases": CLAIMS_EAC_SCENARIOS,
                "source_csv": {
                    "sha256": file_identity(claims_source)["sha256"],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("figure_builder.metadata.git_short_sha", lambda: "abc1234")

    metadata = build_run_metadata(
        [],
        fine=False,
        force=False,
        generated_at=datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc),
        scenario=scenario,
        base_input_dir=tmp_path,
        statewide_claims_source=claims_source,
    )

    statewide = metadata["statewide_claims"]
    assert statewide == {
        "source_path": str(claims_source.resolve()),
        "source_manifest_path": str(
            claims_eac_manifest_path(claims_source).resolve()
        ),
        "model_run_git_sha": "abc1234",
        "scenario_run_timestamps": {
            "baseline_ice_car": "20260817_17",
            "full_electric_ev": "20260817_17",
            "full_electric_ev_coopt": "20260817_18",
        },
        "scenario_cases": CLAIMS_EAC_SCENARIOS,
        "expected_county_count": 47,
        "electricity_variant": "nem3",
    }
    assert len(metadata["inputs"]) == 10
    claims_input = next(
        row
        for row in metadata["inputs"]
        if row["role"] == "statewide_claims_eac_source"
    )
    assert claims_input["path"] == str(claims_source.resolve())
    assert claims_input["sha256"] == file_identity(claims_source)["sha256"]
    assert metadata["run"]["command_argv"] == [
        "python3",
        "-m",
        "figure_builder",
        "all",
        "--claims-source",
        str(claims_source.resolve()),
    ]


def test_build_run_metadata_rejects_naive_timestamp(tmp_path):
    with pytest.raises(ValueError, match="timezone-aware"):
        build_run_metadata(
            [],
            fine=False,
            force=False,
            generated_at=datetime(2026, 8, 17),
            base_input_dir=tmp_path,
        )


def test_write_run_metadata_is_stable_and_human_readable(tmp_path):
    destination = tmp_path / "run_metadata.json"
    write_run_metadata(destination, {"b": 2, "a": 1})

    assert destination.read_text(encoding="utf-8") == '{\n  "a": 1,\n  "b": 2\n}\n'
