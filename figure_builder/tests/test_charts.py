import pandas as pd
import pytest

from figure_builder.charts import plot_pv_batt_vs_capex_compare
from figure_builder.datasets import SWEEP_COLUMNS


def _sweep() -> pd.DataFrame:
    return pd.DataFrame(
        [
            [25.0, 4.0, 10.0, 1_000.0, 0.8, 40.0, 2, 2],
            [500.0, 3.0, 5.0, 1_500.0, 0.7, 40.0, 1, 2],
            [1_022.448, 2.5, 0.0, 2_000.0, 0.6, 40.0, 0, 1],
            [1_460.64, 2.0, 0.0, 2_500.0, 0.5, 40.0, 0, 1],
        ],
        columns=SWEEP_COLUMNS,
    )


def test_market_annotation_uses_exact_observation_not_hardcoded_zero():
    sweep = _sweep()
    before = sweep.loc[2].copy()
    before["batt_kwh"] = 5.5329
    after = sweep.loc[3].copy()
    after["batt_kwh"] = 0.0001515

    fig, meta = plot_pv_batt_vs_capex_compare(
        sweep,
        sweep,
        batt_before=1_022.448,
        batt_after=1_460.64,
        market_before=before,
        market_after=after,
        market_before_resolution="12×24",
        market_after_resolution="8,760 h",
        title="test",
        panel_labels=("before", "after"),
    )
    try:
        text = "\n".join(
            artist.get_text()
            for axis in fig.axes
            for artist in axis.texts
        )
        assert "12×24: battery = 5.53 kWh" in text
        assert "8,760 h: battery = <0.01 kWh" in text
        assert meta["before"]["market_batt_kwh"] == pytest.approx(5.5329)
        assert meta["after"]["market_batt_kwh"] == pytest.approx(0.0001515)
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)


def test_market_annotation_rejects_wrong_price():
    sweep = _sweep()
    before = sweep.loc[1]
    after = sweep.loc[3]

    with pytest.raises(ValueError, match="does not match marker price"):
        plot_pv_batt_vs_capex_compare(
            sweep,
            sweep,
            batt_before=1_022.448,
            batt_after=1_460.64,
            market_before=before,
            market_after=after,
            market_before_resolution="12×24",
            market_after_resolution="8,760 h",
            title="test",
            panel_labels=("before", "after"),
        )
