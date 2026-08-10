import pandas as pd
import pytest

from pipeline.steps.step13_combine_total_annual_costs import calculate_total_annual_costs


def test_total_annual_costs_adds_electricity_and_gas_for_each_plan():
    index = ["baseline", "baseline.solarstorage"]
    electricity = pd.DataFrame(
        index=index,
        data={
            "electricity.PG&E.E-TOU-C": [3_000.0, 2_500.0],
            "electricity.PG&E.E-ELEC": [2_800.0, 2_300.0],
        },
    )
    gas = pd.DataFrame(index=index, data={"gas.PG&E.G-1": [500.0, 500.0]})

    totals = calculate_total_annual_costs(electricity, gas)

    assert list(totals.columns) == [
        "total.PG&E.E-TOU-C+PG&E.G-1",
        "total.PG&E.E-ELEC+PG&E.G-1",
    ]
    assert totals.loc["baseline", "total.PG&E.E-TOU-C+PG&E.G-1"] == pytest.approx(3_500.0)
    assert totals.loc["baseline.solarstorage", "total.PG&E.E-ELEC+PG&E.G-1"] == pytest.approx(
        2_800.0
    )


def test_total_annual_costs_preserves_nbt_column_and_nan_for_non_solar_row():
    index = ["baseline_coopt", "baseline_coopt.solarstorage"]
    electricity = pd.DataFrame(
        index=index,
        data={
            "electricity.PG&E.E-ELEC": [3_000.0, 2_500.0],
            "electricity.PG&E.E-ELEC_NEM3": [float("nan"), 2_480.0],
        },
    )
    gas = pd.DataFrame(index=index, data={"gas.PG&E.G-1": [500.0, 500.0]})

    totals = calculate_total_annual_costs(electricity, gas)
    nbt_column = "total.PG&E.E-ELEC_NEM3+PG&E.G-1"

    assert nbt_column in totals.columns
    assert pd.isna(totals.loc["baseline_coopt", nbt_column])
    assert totals.loc["baseline_coopt.solarstorage", nbt_column] == pytest.approx(2_980.0)


def test_total_annual_costs_propagates_nan_when_gas_scenario_is_missing():
    electricity = pd.DataFrame(
        index=["scenario_a", "scenario_b"],
        data={"electricity.PG&E.E-ELEC": [1_000.0, 2_000.0]},
    )
    gas = pd.DataFrame(index=["scenario_a"], data={"gas.PG&E.G-1": [500.0]})

    totals = calculate_total_annual_costs(electricity, gas)
    column = "total.PG&E.E-ELEC+PG&E.G-1"

    assert totals.loc["scenario_a", column] == pytest.approx(1_500.0)
    assert pd.isna(totals.loc["scenario_b", column])
