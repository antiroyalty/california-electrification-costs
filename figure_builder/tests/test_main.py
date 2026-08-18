from types import SimpleNamespace
from unittest.mock import call, patch

from appliances.incentive_policy import PolicyRegime
from figure_builder.__main__ import (
    _cmd_all,
    _cmd_installer,
    _cmd_market,
    _cmd_sweeps,
)


def test_sweeps_force_rebuilds_both_policy_regimes():
    args = SimpleNamespace(counties=["alameda", "fresno"], force=True, fine=False)

    with patch(
        "figure_builder.__main__.collect_battery_capex_sweep"
    ) as collect, patch("figure_builder.__main__.sweep_csv_path") as cache_path:
        cache_path.side_effect = lambda slug, regime, resolution: (
            f"{slug}-{regime}-{resolution}.csv"
        )

        artifacts = _cmd_sweeps(args)

    assert collect.call_args_list == [
        call(
            "alameda",
            regime=PolicyRegime.POST_ITC_2026,
            force=True,
            fine=False,
        ),
        call(
            "fresno",
            regime=PolicyRegime.POST_ITC_2026,
            force=True,
            fine=False,
        ),
        call(
            "alameda",
            regime=PolicyRegime.ITC_2025,
            force=True,
            fine=False,
        ),
        call(
            "fresno",
            regime=PolicyRegime.ITC_2025,
            force=True,
            fine=False,
        ),
    ]
    assert artifacts == [
        "alameda-post_itc_2026-288.csv",
        "fresno-post_itc_2026-288.csv",
        "alameda-itc_2025-288.csv",
        "fresno-itc_2025-288.csv",
    ]


def test_installer_returns_document_and_sweep_cache_for_metadata(tmp_path):
    doc = tmp_path / "claims.html"
    cache = tmp_path / "fixed-pv.csv"
    cache.write_text("battery_capex_kwh,batt_kwh\n")

    with (
        patch(
            "figure_builder.recipes.build_installer_rule_figure",
            return_value=doc,
        ),
        patch(
            "figure_builder.recipes.installer_rule_sweep_path",
            return_value=cache,
        ),
        patch(
            "figure_builder.__main__.live_prices",
            return_value=SimpleNamespace(regime="post_itc_2026"),
        ),
    ):
        artifacts = _cmd_installer(SimpleNamespace())

    assert artifacts == [str(doc), str(cache)]


def test_market_command_builds_current_law_exact_observations_only():
    args = SimpleNamespace(counties=["alameda"], force=True, fine=False)

    with (
        patch(
            "figure_builder.__main__.collect_market_price_observation"
        ) as collect,
        patch(
            "figure_builder.__main__.market_observation_csv_path"
        ) as cache_path,
    ):
        cache_path.side_effect = lambda slug, regime: f"{slug}-{regime}.csv"
        artifacts = _cmd_market(args)

    assert collect.call_args_list == [
        call("alameda", regime=PolicyRegime.POST_ITC_2026, force=True),
    ]
    assert artifacts == [
        "alameda-post_itc_2026.csv",
    ]


def test_all_passes_cli_run_identity_to_metadata_writer():
    args = SimpleNamespace(counties=None, force=True, fine=False)
    command_names = (
        "sweeps",
        "market",
        "mechanism",
        "installer",
        "counties",
        "tariff_status",
        "statewide",
        "bridge",
        "split",
    )
    patches = [
        patch(f"figure_builder.__main__._cmd_{name}", return_value=[name])
        for name in command_names
    ]

    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
        patches[7],
        patches[8],
        patch("figure_builder.__main__._write_metadata") as write_metadata,
    ):
        artifacts = _cmd_all(args)

    assert artifacts == list(command_names)
    write_metadata.assert_called_once_with(
        list(command_names),
        fine=False,
        force=True,
        requested_counties=None,
    )
