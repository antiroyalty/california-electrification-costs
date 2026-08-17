from types import SimpleNamespace
from unittest.mock import call, patch

from appliances.incentive_policy import PolicyRegime
from figure_builder.__main__ import _cmd_sweeps


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
