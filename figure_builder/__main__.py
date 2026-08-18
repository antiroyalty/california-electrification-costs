#!/usr/bin/env python3
"""CLI driver for figure_builder.

    python3 -m figure_builder sweeps                 # (re)compute all county sweeps
    python3 -m figure_builder sweeps --counties alameda --force
    python3 -m figure_builder market                 # exact current-law market points
    python3 -m figure_builder mechanism              # patch Claim-1 mechanism block
    python3 -m figure_builder counties               # patch Claim-1 county grid
    python3 -m figure_builder bridge                 # render bridge waterfall PNG
    python3 -m figure_builder split                  # split combined -> claim1/2/3.html
    python3 -m figure_builder all                    # rebuild all report inputs and sections

`all` writes a run_metadata.json (regime, git sha, prices, artifacts) so any
figure run is reproducible.
"""
from __future__ import annotations

import argparse

from appliances.incentive_policy import PolicyRegime
from figure_builder import (
    FIG_DIR,
    current_claims_doc,
    market_observation_csv_path,
    sweep_csv_path,
)
from figure_builder.datasets import (
    collect_battery_capex_sweep,
    collect_market_price_observation,
)
from figure_builder.dispatch import CLAIM1_COUNTIES
from figure_builder.pricing import live_prices


SWEEP_REGIMES = (
    PolicyRegime.POST_ITC_2026,
    PolicyRegime.ITC_2025,
)
MARKET_OBSERVATION_REGIMES = (PolicyRegime.POST_ITC_2026,)


def _cmd_sweeps(args) -> list:
    slugs = args.counties or [s for s, _, _ in CLAIM1_COUNTIES]
    out = []
    resolution = "8760" if args.fine else "288"
    for regime in SWEEP_REGIMES:
        prices = live_prices(regime)
        print(
            f"Regime {prices.regime}: solar fixed "
            f"${prices.pv_net_per_kw:,.0f}/kW, battery "
            f"${prices.batt_net_per_kwh:,.0f}/kWh net"
        )
        for slug in slugs:
            print(f"\n{slug}:")
            collect_battery_capex_sweep(
                slug,
                regime=regime,
                force=args.force,
                fine=args.fine,
            )
            out.append(str(sweep_csv_path(slug, prices.regime, resolution)))
    return out


def _cmd_market(args) -> list:
    """Build current-law exact-price, full-chronology Claim 1 observations.

    The 2025 ITC side is explicitly a 12x24 sensitivity: corrected full-year
    Southern California MILPs do not complete within the publication workflow's
    bounded runtime, so the builder must not mislabel them as exact results.
    """

    slugs = args.counties or [slug for slug, _, _ in CLAIM1_COUNTIES]
    out = []
    for regime in MARKET_OBSERVATION_REGIMES:
        prices = live_prices(regime)
        for slug in slugs:
            print(
                f"\nExact 8,760-hour market observation: {slug}, "
                f"{prices.regime}, ${prices.batt_net_per_kwh:,.3f}/kWh"
            )
            collect_market_price_observation(
                slug,
                regime=regime,
                force=args.force,
            )
            out.append(str(market_observation_csv_path(slug, prices.regime)))
    return out


def _cmd_mechanism(args):
    from figure_builder.recipes import build_mechanism_block
    return [str(build_mechanism_block(fine=args.fine))]


def _cmd_counties(args):
    from figure_builder.recipes import build_county_grid
    return [str(build_county_grid(fine=args.fine))]


def _cmd_installer(_args):
    from figure_builder.recipes import (
        build_installer_rule_figure,
        installer_rule_sweep_path,
    )

    doc = build_installer_rule_figure()
    cache = installer_rule_sweep_path("alameda", live_prices().regime)
    if not cache.exists():
        raise FileNotFoundError(f"Installer-rule sweep cache was not written: {cache}")
    return [str(doc), str(cache)]


def _cmd_tariff_status(_args):
    from figure_builder.recipes import build_tariff_status_block
    return [str(build_tariff_status_block())]


def _cmd_bridge(_args):
    from figure_builder.recipes import build_bridge
    return [str(build_bridge())]


def _cmd_split(_args):
    from figure_builder.recipes import split_claims
    return [str(p) for p in split_claims()]


def _cmd_snapshot(_args):
    """Ensure the current commit has its own claims-<sha>.html, seeding it from
    the most recent snapshot if needed. Never overwrites an archived snapshot."""
    doc = current_claims_doc()
    print(f"Current-commit claims doc: {doc.name}")
    return [str(doc)]


def _cmd_all(args):
    artifacts = []
    artifacts += _cmd_sweeps(args)
    artifacts += _cmd_market(args)
    artifacts += _cmd_mechanism(args)
    artifacts += _cmd_installer(args)
    artifacts += _cmd_counties(args)
    artifacts += _cmd_tariff_status(args)
    artifacts += _cmd_bridge(args)
    artifacts += _cmd_split(args)
    _write_metadata(
        artifacts,
        fine=args.fine,
        force=args.force,
        requested_counties=args.counties,
    )
    return artifacts


def _write_metadata(
    artifacts,
    *,
    fine: bool,
    force: bool,
    requested_counties,
) -> None:
    from figure_builder.metadata import build_run_metadata, write_run_metadata

    metadata = build_run_metadata(
        artifacts,
        fine=fine,
        force=force,
        requested_counties=requested_counties,
    )
    path = FIG_DIR / "run_metadata.json"
    write_run_metadata(path, metadata)
    print(f"\nWrote {path}")


_COMMANDS = {
    "snapshot": _cmd_snapshot, "sweeps": _cmd_sweeps, "market": _cmd_market,
    "mechanism": _cmd_mechanism,
    "counties": _cmd_counties, "bridge": _cmd_bridge, "split": _cmd_split,
    "all": _cmd_all,
}


def main() -> None:
    ap = argparse.ArgumentParser(prog="python3 -m figure_builder", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=list(_COMMANDS))
    ap.add_argument("--counties", nargs="*", default=None,
                    help="County slugs (default: all four Claim-1 counties).")
    ap.add_argument("--force", action="store_true",
                    help="Recompute sweeps even if cached.")
    ap.add_argument(
        "--fine",
        action="store_true",
        help="Use full 8,760-hour chronology for sweeps (slow; default is weighted 12x24).",
    )
    args = ap.parse_args()
    artifacts = _COMMANDS[args.command](args)
    print("\nArtifacts:")
    for a in artifacts:
        print(f"  {a}")


if __name__ == "__main__":
    main()
