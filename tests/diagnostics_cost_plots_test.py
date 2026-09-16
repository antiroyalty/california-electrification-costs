import base64

import matplotlib
import pytest

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from helpers.diagnostics_cost_plots import _fig_to_b64  # noqa: E402


@pytest.fixture(autouse=True)
def close_test_figures():
    plt.close("all")
    yield
    plt.close("all")


def test_fig_to_b64_closes_serialized_figure() -> None:
    fig, ax = plt.subplots()
    figure_number = fig.number
    ax.plot([0, 1], [0, 1])

    encoded = _fig_to_b64(fig)

    assert base64.b64decode(encoded).startswith(b"\x89PNG\r\n\x1a\n")
    assert figure_number not in plt.get_fignums()


def test_fig_to_b64_closes_figure_when_serialization_fails(monkeypatch) -> None:
    fig, _ = plt.subplots()
    figure_number = fig.number

    def fail_to_save(*args, **kwargs):
        raise RuntimeError("synthetic save failure")

    monkeypatch.setattr(fig, "savefig", fail_to_save)

    with pytest.raises(RuntimeError, match="synthetic save failure"):
        _fig_to_b64(fig)

    assert figure_number not in plt.get_fignums()


def test_cost_waterfall_includes_battery_replacement_and_remaining_value(monkeypatch):
    from helpers import diagnostics_cost_plots as charts

    monkeypatch.setattr(charts, "read_total_annual_cost", lambda *args, **kwargs: 1200)
    monkeypatch.setattr(charts, "_pv_storage_net_breakdown", lambda *args, **kwargs: {
        "pv_net": 0, "storage_net": 10000,
    })
    monkeypatch.setattr(charts, "_fig_to_b64", lambda fig: [
        bar.get_height() for bar in fig.axes[0].patches
    ])

    values = charts.create_cost_waterfall_chart("unused", "scenario", "housing", "alameda")

    assert values == pytest.approx([1200, 1200, 1116.42, 2316.42], abs=0.01)


def test_storage_cost_chart_includes_battery_replacement_and_remaining_value(monkeypatch):
    from helpers import diagnostics_cost_plots as charts

    monkeypatch.setattr(charts, "estimate_storage_value_upper_bound", lambda *args: 1500)
    monkeypatch.setattr(charts, "read_coopt_capacities", lambda *args: {
        "battery_kwh": 10, "battery_kw": 5,
    })
    monkeypatch.setattr(charts, "_fig_to_b64", lambda fig: [
        bar.get_height() for bar in fig.axes[0].patches
    ])

    values = charts.create_storage_value_vs_cost_chart(
        "unused", "scenario", "housing", "alameda", batt_capex_per_kwh=1000,
    )

    assert values == pytest.approx([1500, 1116.42], abs=0.01)
