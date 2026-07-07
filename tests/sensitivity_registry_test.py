"""Tests for the sensitivity parameter registry (evaluations/sensitivity.py).

Pure structural checks — no pipeline execution. See
sensitivity_runner_test.py for orchestration behavior.
"""
import dataclasses
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from evaluations.sensitivity import SENSITIVITY_PARAMETERS
from pipeline.config import Config


def test_registry_has_discount_rate_and_nbc():
    assert "discount_rate" in SENSITIVITY_PARAMETERS
    assert "nbc_dollars_per_kwh" in SENSITIVITY_PARAMETERS


def test_every_registered_config_field_exists_on_config():
    """If a registry entry points at a Config field that doesn't exist,
    run_sensitivity would fail with a cryptic TypeError deep inside a sweep
    instead of failing fast and clearly."""
    config_fields = {f.name for f in dataclasses.fields(Config)}
    for name, param in SENSITIVITY_PARAMETERS.items():
        assert param.config_field in config_fields, (
            f"SensitivityParameter '{name}' points at Config.{param.config_field}, "
            f"which does not exist on Config."
        )


def test_discount_rate_requires_lp_resolve():
    """Discount rate changes the LP's optimal PV/battery sizing, not just
    report-time annualization — a sweep that skipped the LP resolve would
    silently report the wrong sizes for every rate except the default."""
    assert SENSITIVITY_PARAMETERS["discount_rate"].requires_lp_resolve is True


def test_nbc_does_not_require_lp_resolve():
    """Documents the current methodology: NBC affects only step12 billing,
    not the LP's price series. If this ever changes, this test should be
    updated deliberately alongside the LP wiring, not silently."""
    assert SENSITIVITY_PARAMETERS["nbc_dollars_per_kwh"].requires_lp_resolve is False
