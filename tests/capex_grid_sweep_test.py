from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.capex_grid_sweep import GridSpec, run


def test_run_uses_resolved_tariff_plan_in_plot_title(tmp_path):
    county_dir = tmp_path / "alameda"
    county_dir.mkdir()
    (county_dir / "weather_TMY_alameda.csv").touch()
    (county_dir / "combined_profiles_baseline_alameda.csv").touch()

    tariff = SimpleNamespace(
        import_schedule=SimpleNamespace(
            plan_name="E-ELEC",
            rates_for=lambda timestamps: [0.30] * 8760,
        ),
        export_schedule=SimpleNamespace(rates_for=lambda timestamps: [0.05] * 8760),
        acc_plus_rate=0.0088,
    )
    result = SimpleNamespace(
        pv_kw=3.0,
        batt_kwh=10.0,
        batt_kw=5.0,
        total_cost=2_000.0,
        capex_annual=1_000.0,
        import_cost=1_100.0,
        export_credit=100.0,
        degradation_cost=0.0,
        meter_binary_count=2,
        solver_rounds=2,
    )

    with (
        patch("scripts.capex_grid_sweep.get_scenario_path", return_value=str(tmp_path)),
        patch(
            "scripts.capex_grid_sweep.prepare_weather_and_load",
            return_value=(object(), [1.0] * 8760),
        ),
        patch("scripts.capex_grid_sweep.pv_timeseries_ac_kwh", return_value=[0.5] * 8760),
        patch(
            "scripts.capex_grid_sweep.resolve_county_service_assignment",
            return_value=SimpleNamespace(utility="PG&E"),
        ),
        patch("scripts.capex_grid_sweep.TariffCatalog.bundle", return_value=tariff),
        patch("scripts.capex_grid_sweep.full_year_hourly_index", return_value=range(8760)),
        patch("scripts.capex_grid_sweep._solve_lp", return_value=result),
        patch("scripts.capex_grid_sweep._plot_heatmap") as plot,
    ):
        csv_path, png_path = run(
            base_input_dir=str(tmp_path),
            experiments_root=str(tmp_path / "experiments"),
            scenario="baseline",
            housing_type="single-family-detached",
            county="Alameda County",
            grid=GridSpec(2_000, 2_000, 100, 500, 500, 100),
            plan_override=None,
            discount_rate=0.07,
            pv_life_yrs=25,
            batt_life_yrs=15,
            batt_capex_per_kw=0.0,
            allow_grid_charging=False,
            allow_batt_export=True,
            fine=False,
            year=2026,
            max_battery_kwh=40.0,
        )

    assert Path(csv_path).exists()
    assert png_path.endswith("capex_grid_alameda.png")
    assert plot.call_args.kwargs["title"].endswith("(alameda, E-ELEC)")
