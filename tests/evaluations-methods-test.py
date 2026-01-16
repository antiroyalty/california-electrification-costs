import importlib
import json
import math
import os
import sys

import pandas as pd
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from evaluations import eac, energy, incentives, lcoe, payback_periods, tariffs, vehicles
npv_module = importlib.import_module("evaluations.npv")


def _repo_root() -> str:
    return REPO_ROOT


def _load_manifest() -> dict:
    path = os.path.join(_repo_root(), "docs", "methods.yaml")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_methods_manifest_loads() -> None:
    manifest = _load_manifest()
    assert isinstance(manifest, dict)
    assert manifest, "methods manifest is empty"


def test_methods_manifest_code_refs_exist() -> None:
    manifest = _load_manifest()
    root = _repo_root()
    for key, entry in manifest.items():
        for ref in entry.get("code", []):
            path = ref.split(":", 1)[0]
            abs_path = os.path.join(root, path)
            assert os.path.exists(abs_path), f"{key}: missing file {path}"
            if ":" in ref:
                symbol = ref.split(":", 1)[1]
                with open(abs_path, "r", encoding="utf-8") as f:
                    content = f.read()
                assert symbol in content, f"{key}: symbol {symbol} not found in {path}"


def test_manifest_covers_evaluations_modules() -> None:
    manifest = _load_manifest()
    referenced = set()
    for entry in manifest.values():
        for ref in entry.get("code", []):
            path = ref.split(":", 1)[0]
            if path.startswith("evaluations/"):
                referenced.add(path)

    required = {
        "evaluations/constants.py",
        "evaluations/eac.py",
        "evaluations/energy.py",
        "evaluations/incentives.py",
        "evaluations/lcoe.py",
        "evaluations/npv.py",
        "evaluations/payback_periods.py",
        "evaluations/tariffs.py",
        "evaluations/vehicles.py",
    }
    missing = sorted(required - referenced)
    assert not missing, f"methods manifest missing evaluations modules: {missing}"


def test_example_calculations() -> None:
    assert energy.therms_to_kwh(1.0) == pytest.approx(29.3001)
    assert energy.effective_price_per_kwh(100.0, 50.0) == pytest.approx(2.0)

    assert npv_module.annuity_factor(0.0, 10) == pytest.approx(0.1)
    assert npv_module.npv(0.1, [100.0, 100.0]) == pytest.approx(190.9090909)

    crf = eac.crf(0.1, 2)
    expected_crf = (0.1 * (1.1**2)) / ((1.1**2) - 1.0)
    assert crf == pytest.approx(expected_crf)

    pv_net, st_net = incentives.apply_pv_storage_incentives(
        100.0, 50.0, 10.0, 5.0, incentive="half_incentives"
    )
    assert pv_net == pytest.approx(95.0)
    assert st_net == pytest.approx(47.5)

    sav, typ = payback_periods.choose_annual_savings(200.0, 180.0, 150.0)
    assert sav == pytest.approx(50.0)
    assert typ == "with_solar"
    assert payback_periods.compute_payback_years(1000.0, 100.0) == pytest.approx(10.0)
    assert math.isinf(payback_periods.compute_payback_years(1000.0, 0.0))

    row = pd.Series(
        {
            "electricity.PGE.E-TOU-D": 300.0,
            "electricity.PGE.E-TOU-D_NEM3": 250.0,
            "gas.PGE.G-1": 100.0,
        }
    )
    val_nem3 = tariffs.select_row_value_for_plan(
        row, plan_preference=["E-TOU-D"], variant="nem3"
    )
    val_retail = tariffs.select_row_value_for_plan(
        row, plan_preference=["E-TOU-D"], variant="retail"
    )
    assert val_nem3 == pytest.approx(250.0)
    assert val_retail == pytest.approx(300.0)

    df = pd.DataFrame(
        [
            {
                "county_slug": "alameda",
                "appliance_category": "electric",
                "appliance_type": "vehicle_charging",
                "annual_operating_cost": 100.0,
            },
            {
                "county_slug": "alameda",
                "appliance_category": "gas",
                "appliance_type": "vehicle_fuel",
                "annual_operating_cost": 200.0,
            },
        ]
    )
    adders = vehicles.vehicle_annual_adders_from_ledger(df)
    assert adders.loc["alameda", "ev_operating"] == pytest.approx(100.0)
    assert adders.loc["alameda", "ice_operating"] == pytest.approx(200.0)

    lcoe_val = lcoe.lcoe_crf_simple(1000.0, 0.0, 1000.0, 0.1, 10)
    expected = eac.crf(0.1, 10)
    assert lcoe_val == pytest.approx(expected)

    pv_energy = lcoe.present_value_energy(1000.0, 2, 0.1, degradation_rate=0.1)
    expected_pv = (1000.0 / 1.1) + (900.0 / (1.1**2))
    assert pv_energy == pytest.approx(expected_pv)
