import matplotlib.pyplot as plt

from helpers.step9_plotting_helper import plot_first_weeks


def test_plot_first_weeks_can_close_fire_and_forget_figure():
    values = [0.0] * 8760

    fig, _ = plot_first_weeks(
        load_kwh=values,
        pv_ac_kwh=values,
        batt_to_load_kwh=values,
        grid_to_load_kwh=values,
        show=False,
        close=True,
    )

    assert fig.number not in plt.get_fignums()
