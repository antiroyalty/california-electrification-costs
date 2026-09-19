from pathlib import Path

import pandas as pd
import pytest

from pipeline.steps.step20_no_solar_storage_electrification import (
    collect_eac_no_pv,
    collect_eac_no_pv_by_county,
)
from pipeline.steps import step21_compare_eac_with_vs_without as step21
from helpers.plot_scenario_comparison_helper import (
    collect_eac_components,
    collect_eac_components_by_county,
)


HOUSING_TYPE = "single-family-detached"
SCENARIO = "baseline_coopt"
PLAN_PREFERENCES = ["E-TOU-D", "TOU-D-4-9PM", "TOU-DR1"]


def _write_ledger(base_dir, rows, scenario=SCENARIO):
    directory = base_dir / "capital_costs"
    directory.mkdir(exist_ok=True)
    path = directory / f"capital_costs_{scenario}_single_family_detached.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _zero_cost_equipment(county="alameda"):
    return {
        "county_slug": county,
        "incentive_scenario": "full_incentives",
        "appliance_category": "electric",
        "appliance_type": "appliances",
        "net_cost": 0.0,
        "base_cost": 0.0,
        "lifetime_years": 15,
        "annual_operating_cost": 0.0,
    }


def _write_bill_results(
    base_dir: Path,
    county_slug: str,
    electricity_values: dict[str, float],
    gas_bill: float,
) -> None:
    results_dir = base_dir / SCENARIO / HOUSING_TYPE / county_slug / "results"
    electricity_dir = results_dir / "electricity"
    gas_dir = results_dir / "gas"
    electricity_dir.mkdir(parents=True)
    gas_dir.mkdir(parents=True)

    electricity_row = {"scenario": SCENARIO, **electricity_values}
    pd.DataFrame([electricity_row]).to_csv(
        electricity_dir
        / f"RESULTS_electricity_annual_costs_{county_slug}_20260814_11.csv",
        index=False,
    )
    pd.DataFrame(
        [{"scenario": SCENARIO, "gas.default": gas_bill}]
    ).to_csv(
        gas_dir / f"RESULTS_gas_annual_costs_{county_slug}_20260814_11.csv",
        index=False,
    )


def test_step20_uses_configured_retail_plan_for_aggregate_and_county(
    tmp_path: Path,
) -> None:
    # Zero equipment cost is an explicit input, not an absent ledger.
    _write_ledger(tmp_path, [_zero_cost_equipment(c) for c in ("alameda", "los-angeles")])
    _write_bill_results(
        tmp_path,
        "alameda",
        {
            "electricity.PG&E.E-TOU-C": 900.0,
            "electricity.PG&E.E-TOU-D": 300.0,
            "electricity.PG&E.E-ELEC_NEM3": 200.0,
        },
        gas_bill=100.0,
    )
    _write_bill_results(
        tmp_path,
        "los-angeles",
        {
            "electricity.SCE.TOU-D-5-8PM": 800.0,
            "electricity.SCE.TOU-D-4-9PM": 500.0,
            "electricity.SCE.TOU-D-PRIME_NEM3": 350.0,
        },
        gas_bill=200.0,
    )

    aggregate = collect_eac_no_pv(
        str(tmp_path),
        HOUSING_TYPE,
        [SCENARIO],
        ["Alameda County", "Los Angeles County"],
        electricity_plan_preference=PLAN_PREFERENCES,
    )
    by_county = collect_eac_no_pv_by_county(
        str(tmp_path),
        HOUSING_TYPE,
        [SCENARIO],
        ["Alameda County", "Los Angeles County"],
        electricity_plan_preference=PLAN_PREFERENCES,
    ).set_index("county_slug")

    assert aggregate.loc[0, "annual_bill_electric"] == pytest.approx(400.0)
    assert aggregate.loc[0, "annual_bill_gas"] == pytest.approx(150.0)
    assert by_county.loc["alameda", "annual_bill_electric"] == pytest.approx(300.0)
    assert by_county.loc["los-angeles", "annual_bill_electric"] == pytest.approx(
        500.0
    )
    assert by_county.loc["alameda", "annual_bill_gas"] == pytest.approx(100.0)
    assert by_county.loc["los-angeles", "annual_bill_gas"] == pytest.approx(200.0)


def _with_county_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "scenario": SCENARIO,
                "county_slug": county,
                "capex_pv": 100.0,
                "capex_storage": 0.0,
                "capex_electric": 0.0,
                "capex_gas": 0.0,
                "vehicle_om": 0.0,
                "annual_bill_electric": bill,
                "annual_bill_gas": 100.0,
            }
            for county, bill in (("alameda", 600.0), ("los-angeles", 800.0))
        ]
    )


def _no_county_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "scenario": SCENARIO,
                "county_slug": county,
                "capex_electric": 0.0,
                "capex_gas": 0.0,
                "vehicle_om": 0.0,
                "annual_bill_electric": bill,
                "annual_bill_gas": 100.0,
            }
            for county, bill in (("alameda", 700.0), ("los-angeles", 950.0))
        ]
    )


def test_step21_process_writes_reconciled_county_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with_aggregate = _with_county_rows().drop(columns="county_slug").mean(
        numeric_only=True
    ).to_frame().T
    with_aggregate["scenario"] = SCENARIO
    no_aggregate = _no_county_rows().drop(columns="county_slug").mean(
        numeric_only=True
    ).to_frame().T
    no_aggregate["scenario"] = SCENARIO

    captured: dict[str, dict] = {}

    def collect_with(*args, **kwargs):
        captured["with"] = kwargs
        return with_aggregate

    def collect_without(*args, **kwargs):
        captured["without"] = kwargs
        return no_aggregate

    monkeypatch.setattr(step21, "collect_eac_components", collect_with)
    monkeypatch.setattr(step21, "collect_eac_no_pv", collect_without)
    monkeypatch.setattr(
        step21,
        "collect_eac_components_by_county",
        lambda *args, **kwargs: _with_county_rows(),
    )
    monkeypatch.setattr(
        step21,
        "collect_eac_no_pv_by_county",
        lambda *args, **kwargs: _no_county_rows(),
    )
    monkeypatch.setattr(step21, "git_short_sha", lambda: "testsha")

    step21.process(
        "unused",
        str(tmp_path),
        HOUSING_TYPE,
        SCENARIO,
        ["Alameda County", "Los Angeles County"],
        plan_preference=PLAN_PREFERENCES,
        electricity_variant="nem3",
    )

    output_path = tmp_path / "step21_with_vs_without_by_county_gtestsha.csv"
    result = pd.read_csv(output_path).set_index("county_slug")
    assert len(result) == 2
    assert result.loc["alameda", "total_eac"] == pytest.approx(800.0)
    assert result.loc["alameda", "total_eac_no_pv"] == pytest.approx(800.0)
    assert result.loc["alameda", "delta_with_minus_without"] == pytest.approx(0.0)
    assert result.loc["los-angeles", "delta_with_minus_without"] == pytest.approx(
        -50.0
    )
    assert captured["with"]["electricity_plan_preference"] == PLAN_PREFERENCES
    assert captured["with"]["electricity_variant"] == "nem3"
    assert captured["without"]["electricity_plan_preference"] == PLAN_PREFERENCES


def test_step21_rejects_nonmatching_county_coverage() -> None:
    no_rows = _no_county_rows().query("county_slug == 'alameda'")

    with pytest.raises(ValueError, match="do not cover the same rows"):
        step21._build_county_comparison(_with_county_rows(), no_rows)


def _write_household_case(base_dir, scenario):
    """Write distinct equipment, fuel, and solar costs for an accounting example."""
    electric = scenario == "full_electric_ev_coopt"
    category = "electric" if electric else "gas"
    rows = []
    for incentive, appliance_net, vehicle_net in (
        ("full_incentives", 1500, 18000),
        ("half_incentives", 1750, 20000),
        ("no_incentives", 2000, 22000),
    ):
        for kind, base, net, life, operating in (
            ("heating", 2000 if electric else 600, appliance_net, 15 if electric else 10, 0),
            ("vehicle_charging" if electric else "vehicle_fuel",
             22000 if electric else 12000, vehicle_net, 12, -60 if electric else 120),
        ):
            rows.append({
                **_zero_cost_equipment(), "incentive_scenario": incentive,
                "appliance_category": category, "appliance_type": kind,
                "base_cost": base, "net_cost": net, "lifetime_years": life,
                "annual_operating_cost": operating,
            })
        for kind in ("solar", "storage"):
            rows.append({
                **_zero_cost_equipment(), "incentive_scenario": incentive,
                "appliance_type": kind, "base_cost": 90000, "net_cost": 90000,
            })
    ledger_path = _write_ledger(base_dir, rows, scenario)
    pv_path = ledger_path.with_name(ledger_path.name.replace("capital_costs_", "capital_costs_summary_with_pv_"))
    pd.DataFrame([{
        "county_slug": "alameda", "pv_capex": 3300, "storage_capex": 10000,
        "pv_incentives_full": 0, "storage_incentives_full": 0,
    }]).to_csv(pv_path, index=False)
    for fuel, values in (
        ("electricity", {"electricity.PG&E.E-TOU-D": 900,
                         "electricity.PG&E.E-ELEC_NEM3": 600}),
        ("gas", {"gas.default": 0 if electric else 300}),
    ):
        directory = base_dir / scenario / HOUSING_TYPE / "alameda" / "results" / fuel
        directory.mkdir(parents=True)
        pd.DataFrame([
            {"scenario": scenario, **values},
            {"scenario": f"{scenario}.solarstorage", **values},
        ]).to_csv(directory / f"RESULTS_{fuel}_annual_costs_alameda_20260814_11.csv", index=False)
    return ledger_path, pv_path


@pytest.mark.parametrize("scenario", ["baseline_ice_car_coopt", "full_electric_ev_coopt"])
@pytest.mark.parametrize("rate", [0.0, 0.07])
@pytest.mark.parametrize("incentive,appliance_net,vehicle_net", [
    ("full_incentives", 1500, 18000),
    ("half_incentives", 1750, 20000),
    ("no_incentives", 2000, 22000),
])
def test_shared_reports_match_independent_household_costs(
    tmp_path, scenario, rate, incentive, appliance_net, vehicle_net,
):
    """Annualize explicit purchases independently and retain negative EV O&M."""
    _write_household_case(tmp_path, scenario)
    args = (str(tmp_path), HOUSING_TYPE, [scenario], ["Alameda County"])
    kwargs = dict(incentive=incentive, discount_rate=rate,
                  electricity_plan_preference=PLAN_PREFERENCES)
    without = collect_eac_no_pv_by_county(*args, **kwargs).iloc[0]
    with_solar = collect_eac_components_by_county(*args, **kwargs).iloc[0]
    annualize = lambda cost, life: cost / sum((1 + rate) ** -t for t in range(1, life + 1))
    electric = scenario == "full_electric_ev_coopt"
    expected_electric = annualize(appliance_net, 15) + annualize(vehicle_net, 12) if electric else 0
    expected_gas = 0 if electric else annualize(600, 10) + annualize(12000, 12)
    expected_operating = -60 if electric else 120
    for row in (without, with_solar):
        assert row["capex_electric"] == pytest.approx(expected_electric)
        assert row["capex_gas"] == pytest.approx(expected_gas)
        assert row["vehicle_om"] == expected_operating
        assert row["annual_bill_gas"] == (0 if electric else 300)
    assert without["annual_bill_electric"] == 900
    assert with_solar["annual_bill_electric"] == 600
    expected_total = expected_electric + expected_gas + expected_operating + 900 + (0 if electric else 300)
    assert without.drop(["scenario", "county_slug"]).sum() == pytest.approx(expected_total)
    for collector, county_row in ((collect_eac_no_pv, without), (collect_eac_components, with_solar)):
        aggregate = collector(*args, **kwargs).iloc[0]
        pd.testing.assert_series_equal(aggregate, county_row.drop("county_slug"))


@pytest.mark.parametrize(
    "scenario,vehicle_type",
    [
        ("baseline_ice_car_coopt", "vehicle_fuel"),
        ("full_electric_ev_coopt", "vehicle_charging"),
    ],
)
def test_publication_eac_selects_the_requested_vehicle_incentive_case(
    tmp_path, scenario, vehicle_type,
):
    """Publication EAC selects alternative cases without summing or pinning one."""
    ledger_path, _ = _write_household_case(tmp_path, scenario)
    ledger = pd.read_csv(ledger_path)
    operating_by_incentive = {
        "full_incentives": -40,
        "half_incentives": 0,
        "no_incentives": 80,
    }
    vehicle_rows = ledger["appliance_type"] == vehicle_type
    ledger.loc[vehicle_rows, "annual_operating_cost"] = ledger.loc[
        vehicle_rows, "incentive_scenario"
    ].map(operating_by_incentive)
    ledger.to_csv(ledger_path, index=False)

    for incentive, expected in operating_by_incentive.items():
        result = collect_eac_no_pv_by_county(
            str(tmp_path),
            HOUSING_TYPE,
            [scenario],
            ["Alameda County"],
            incentive=incentive,
            electricity_plan_preference=PLAN_PREFERENCES,
        ).iloc[0]
        assert result["vehicle_om"] == expected


@pytest.mark.parametrize("collector", [collect_eac_no_pv, collect_eac_no_pv_by_county])
def test_no_solar_requires_a_ledger_even_when_bills_exist(tmp_path, collector):
    _write_bill_results(tmp_path, "alameda", {"electricity.PG&E.E-TOU-D": 300}, 100)
    with pytest.raises(FileNotFoundError, match="Capital ledger"):
        collector(str(tmp_path), HOUSING_TYPE, [SCENARIO], ["Alameda County"])


@pytest.mark.parametrize("problem,message", [
    ("missing_column", "missing columns"),
    ("missing_county", "No capital ledger rows"),
    ("missing_incentive", "No capital ledger rows"),
    ("missing_label", "non-empty text"),
    ("duplicate", "duplicate"),
    ("category", "appliance_category"),
    ("text_cost", "net_cost must be numeric"),
    ("missing_cost", "base_cost must be finite"),
    ("infinite_operating", "annual_operating_cost must be finite"),
    ("zero_life", "lifetime_years must be positive"),
    ("negative_life", "lifetime_years must be positive"),
    ("missing_life", "lifetime_years must be finite"),
])
@pytest.mark.parametrize("with_solar", [False, True])
def test_shared_reports_reject_invalid_capital_data(tmp_path, problem, message, with_solar):
    scenario = "full_electric_ev_coopt"
    path, _ = _write_household_case(tmp_path, scenario)
    frame = pd.read_csv(path)
    if problem == "missing_column":
        frame = frame.drop(columns="lifetime_years")
    elif problem == "missing_county":
        frame["county_slug"] = "los-angeles"
    elif problem == "missing_incentive":
        frame = frame[frame["incentive_scenario"] != "full_incentives"]
    elif problem == "duplicate":
        frame = pd.concat([frame, frame.iloc[[0]]])
    else:
        field, value = {
            "missing_label": ("appliance_type", None),
            "category": ("appliance_category", "unknown"),
            "text_cost": ("net_cost", "unknown"),
            "missing_cost": ("base_cost", float("nan")),
            "infinite_operating": ("annual_operating_cost", float("inf")),
            "zero_life": ("lifetime_years", 0),
            "negative_life": ("lifetime_years", -1),
            "missing_life": ("lifetime_years", float("nan")),
        }[problem]
        frame[field] = frame[field].astype(object)
        frame.loc[0, field] = value
    frame.to_csv(path, index=False)
    with pytest.raises((ValueError, KeyError), match=message):
        collect_eac_components_by_county(
            str(tmp_path), HOUSING_TYPE, [scenario], ["Alameda County"],
            with_solar=with_solar,
        )


def test_no_solar_does_not_require_pv_summary_or_use_latest_bill_when_timestamp_given(tmp_path):
    scenario = "full_electric_ev_coopt"
    _, pv_path = _write_household_case(tmp_path, scenario)
    pv_path.unlink()
    for fuel in ("electricity", "gas"):
        directory = tmp_path / scenario / HOUSING_TYPE / "alameda" / "results" / fuel
        old = directory / f"RESULTS_{fuel}_annual_costs_alameda_20260814_11.csv"
        newer = pd.read_csv(old)
        newer.iloc[:, 1:] = 9999
        newer.to_csv(directory / f"RESULTS_{fuel}_annual_costs_alameda_20260815_11.csv", index=False)
    args = (str(tmp_path), HOUSING_TYPE, [scenario], ["Alameda County"])
    for collector in (collect_eac_no_pv, collect_eac_no_pv_by_county):
        row = collector(*args, timestamp="20260814_11",
                        electricity_plan_preference=PLAN_PREFERENCES).iloc[0]
        assert row["annual_bill_electric"] == 900
        assert row["annual_bill_gas"] == 0
        with pytest.raises(FileNotFoundError, match="timestamp 20260816_11"):
            collector(*args, timestamp="20260816_11")
    with pytest.raises(FileNotFoundError, match="Capital summary with PV"):
        collect_eac_components_by_county(*args)
