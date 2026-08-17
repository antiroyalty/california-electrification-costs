from types import SimpleNamespace
from unittest.mock import call, patch

from appliances.incentive_policy import PolicyRegime
from figure_builder.__main__ import _cmd_all, _cmd_sweeps


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


def test_all_passes_cli_run_identity_to_metadata_writer():
    args = SimpleNamespace(counties=None, force=True, fine=False)
    command_names = ("sweeps", "mechanism", "counties", "bridge", "split")
    patches = [
        patch(f"figure_builder.__main__._cmd_{name}", return_value=[name])
        for name in command_names
    ]

    with patches[0], patches[1], patches[2], patches[3], patches[4], patch(
        "figure_builder.__main__._write_metadata"
    ) as write_metadata:
        artifacts = _cmd_all(args)

    assert artifacts == list(command_names)
    write_metadata.assert_called_once_with(
        list(command_names),
        fine=False,
        force=True,
        requested_counties=None,
    )
