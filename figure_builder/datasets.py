"""Collectors: run the model, return tidy DataFrames.

Follows the repo's established `collect_*` convention (see
`helpers/plot_scenario_comparison_helper.py`). The collectors replace the old
one-off `run_sweeps.py`: one builds the declared capex sensitivity and the other
builds the exact current-law 8,760-hour market observation used in publication
annotations.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Mapping, Optional, Sequence

import pandas as pd

from tariffs import ExportCompensationRegime

from figure_builder import (
    REPO,
    SWEEP_DIR,
    git_short_sha,
    market_observation_csv_path,
    sweep_csv_path,
)
from figure_builder.dispatch import (
    BASE_INPUT_DIR,
    DEFAULT_SCENARIO,
    HOUSING_TYPE,
    SWEEP_POINTS,
    county_dispatch_inputs,
)
from figure_builder.pricing import live_prices


@dataclass(frozen=True)
class SweepModelSettings:
    """Fixed modeling choices shared by the sweep solver and run metadata."""

    billing_year: int = 2026
    max_battery_kwh: float = 40.0
    max_pv_to_annual_load_ratio: float = 1.5
    allow_grid_charging: bool = False
    allow_battery_export: bool = True
    battery_power_cost_usd_per_kw: float = 0.0
    battery_degradation_cost_usd_per_kwh: float = 0.0
    pv_lifetime_years: int = 25
    battery_lifetime_years: int = 15
    discount_rate: float = 0.07
    solver_backend: str = "highs"


SWEEP_MODEL_SETTINGS = SweepModelSettings()

SWEEP_COLUMNS = [
    "battery_capex_kwh",
    "pv_kw",
    "batt_kwh",
    "total_cost",
    "coverage",
    "max_battery_kwh",
    "meter_binary_count",
    "solver_rounds",
]

MARKET_OBSERVATION_COLUMNS = [
    *SWEEP_COLUMNS,
    "scenario",
    "policy_regime",
    "interval_count",
]

CLAIMS_EAC_SCENARIOS = {
    "baseline_ice_car": "gas_ice_reference",
    "full_electric_ev": "fixed_pv_electric",
    "full_electric_ev_coopt": "cooptimized_electric",
}
EAC_COMPONENT_COLUMNS = [
    "capex_pv",
    "capex_storage",
    "capex_electric",
    "capex_gas",
    "annual_bill_electric",
    "annual_bill_gas",
    "vehicle_om",
]
CLAIMS_ELECTRICITY_PLAN_PREFERENCE = (
    "E-TOU-D",
    "TOU-D-4-9PM",
    "TOU-DR1",
)
CLAIMS_SOURCE_MANIFEST_SCHEMA_VERSION = 1


def claims_eac_source_path(run_sha: str | None = None) -> Path:
    """Claims-only EAC source assembled from a clean model run SHA."""

    sha = run_sha or git_short_sha()
    return REPO / "analysis_results" / f"claims_eac_by_county_nem3_g{sha}.csv"


def claims_eac_manifest_path(source: str | Path) -> Path:
    """Sidecar receipt for one normalized statewide claims source."""

    return Path(source).with_suffix(".manifest.json")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_display_path(path: str | Path) -> str:
    """Use a portable path for repository-owned source artifacts."""

    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(REPO.resolve()))
    except ValueError:
        return str(resolved)


def load_claims_eac_manifest(source: str | Path) -> dict:
    """Load and verify the source receipt, including the CSV fingerprint."""

    source_path = Path(source)
    manifest_path = claims_eac_manifest_path(source_path)
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Claims 2/3 source manifest not found: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != CLAIMS_SOURCE_MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported Claims 2/3 source manifest schema: "
            f"{payload.get('schema_version')}"
        )
    if payload.get("scenario_cases") != CLAIMS_EAC_SCENARIOS:
        raise ValueError("Claims 2/3 source manifest scenario mapping does not match")
    model_run_sha = payload.get("model_git_sha")
    if not isinstance(model_run_sha, str) or not re.fullmatch(
        r"[0-9a-f]{7,40}", model_run_sha
    ):
        raise ValueError("Claims 2/3 source manifest has an invalid model_git_sha")
    run_timestamps = payload.get("scenario_run_timestamps")
    if not isinstance(run_timestamps, dict) or set(run_timestamps) != set(
        CLAIMS_EAC_SCENARIOS
    ):
        raise ValueError(
            "Claims 2/3 source manifest must identify all scenario run timestamps"
        )
    if any(
        not isinstance(value, str) or not re.fullmatch(r"\d{8}_\d{2}", value)
        for value in run_timestamps.values()
    ):
        raise ValueError(
            "Claims 2/3 source manifest timestamps must use YYYYMMDD_HH"
        )
    source_identity = payload.get("source_csv")
    if not isinstance(source_identity, dict):
        raise ValueError("Claims 2/3 source manifest is missing source_csv identity")
    actual_sha256 = _file_sha256(source_path)
    if source_identity.get("sha256") != actual_sha256:
        raise ValueError(
            "Claims 2/3 source CSV fingerprint does not match its manifest"
        )
    return payload


def expected_claim_counties() -> set[str]:
    """The repository's explicit 47-county research domain."""

    from helpers.main_helpers import (
        central_counties,
        norcal_counties,
        socal_counties,
        slugify_county_name,
    )

    return {
        slugify_county_name(county)
        for county in norcal_counties + central_counties + socal_counties
    }


def _validate_claims_eac_frame(
    frame: pd.DataFrame,
    *,
    expected_counties: set[str],
) -> pd.DataFrame:
    """Validate and normalize the exact case/county EAC table."""

    required = ["scenario", "county_slug", *EAC_COMPONENT_COLUMNS]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"Claims 2/3 EAC source is missing columns: {missing}")
    selected = frame[frame["scenario"].isin(CLAIMS_EAC_SCENARIOS)].copy()
    selected["case"] = selected["scenario"].map(CLAIMS_EAC_SCENARIOS)
    if not expected_counties:
        raise ValueError("Claims 2/3 expected county set cannot be empty")
    if selected[["scenario", "county_slug"]].isna().any().any():
        raise ValueError("Claims 2/3 EAC source has missing scenario/county identity")
    duplicates = selected.duplicated(["scenario", "county_slug"], keep=False)
    if duplicates.any():
        keys = selected.loc[duplicates, ["scenario", "county_slug"]].to_dict("records")
        raise ValueError(f"Claims 2/3 EAC source has duplicate keys: {keys[:5]}")
    for scenario in CLAIMS_EAC_SCENARIOS:
        actual = set(selected.loc[selected["scenario"] == scenario, "county_slug"])
        if actual != expected_counties:
            missing_counties = sorted(expected_counties - actual)
            extra_counties = sorted(actual - expected_counties)
            raise ValueError(
                f"{scenario} county coverage mismatch: missing={missing_counties}, "
                f"extra={extra_counties}"
            )
    numeric = selected[EAC_COMPONENT_COLUMNS].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        bad = numeric.isna().any(axis=1)
        keys = selected.loc[bad, ["scenario", "county_slug"]].to_dict("records")
        raise ValueError(f"Claims 2/3 EAC source has missing/non-numeric costs: {keys[:5]}")
    if not all(math.isfinite(value) for value in numeric.to_numpy().ravel()):
        raise ValueError("Claims 2/3 EAC source has non-finite costs")
    if (numeric < 0.0).any().any():
        bad = (numeric < 0.0).any(axis=1)
        keys = selected.loc[bad, ["scenario", "county_slug"]].to_dict("records")
        raise ValueError(f"Claims 2/3 EAC source has negative costs: {keys[:5]}")
    selected[EAC_COMPONENT_COLUMNS] = numeric
    selected["total_eac"] = numeric.sum(axis=1)
    if (selected["total_eac"] <= 0.0).any():
        raise ValueError("Claims 2/3 EAC totals must be positive")
    return selected[
        ["scenario", "case", "county_slug", *EAC_COMPONENT_COLUMNS, "total_eac"]
    ].sort_values(["county_slug", "scenario"]).reset_index(drop=True)


def collect_claims_eac_results(
    source: str | Path | None = None,
    *,
    expected_counties: set[str] | None = None,
    require_manifest: bool = True,
) -> pd.DataFrame:
    """Load and strictly validate the three statewide EAC cases for Claims 2/3."""

    path = Path(source) if source is not None else claims_eac_source_path()
    if not path.is_file():
        raise FileNotFoundError(
            f"Claims 2/3 EAC source not found: {path}. Run baseline_ice_car, "
            "full_electric_ev, and full_electric_ev_coopt at the current clean SHA."
        )
    if require_manifest:
        load_claims_eac_manifest(path)
    frame = pd.read_csv(path)
    expected = (
        expected_counties
        if expected_counties is not None
        else expected_claim_counties()
    )
    selected = _validate_claims_eac_frame(frame, expected_counties=expected)
    selected.attrs["source_path"] = str(path)
    return selected


def build_claims_eac_source(
    *,
    model_run_sha: str,
    run_timestamps: Mapping[str, str],
    source: str | Path | None = None,
    base_input_dir: str | Path = BASE_INPUT_DIR,
    completion_dir: str | Path = REPO / "analysis_results" / "county_diagnostics",
    expected_counties: set[str] | None = None,
) -> Path:
    """Normalize the three explicit completed scenario runs for Claims 2/3."""

    if not re.fullmatch(r"[0-9a-f]{7,40}", model_run_sha):
        raise ValueError("model_run_sha must be a 7-40 character lowercase Git SHA")
    timestamps = dict(run_timestamps)
    expected_scenarios = set(CLAIMS_EAC_SCENARIOS)
    if set(timestamps) != expected_scenarios:
        raise ValueError(
            "Claims 2/3 run timestamps must identify exactly "
            f"{sorted(expected_scenarios)}"
        )
    invalid_timestamps = {
        scenario: timestamp
        for scenario, timestamp in timestamps.items()
        if not re.fullmatch(r"\d{8}_\d{2}", str(timestamp))
    }
    if invalid_timestamps:
        raise ValueError(
            f"Claims 2/3 run timestamps must use YYYYMMDD_HH: {invalid_timestamps}"
        )
    counties = (
        expected_claim_counties()
        if expected_counties is None
        else expected_counties
    )
    if not counties:
        raise ValueError("Claims 2/3 expected county set cannot be empty")
    markers = [
        Path(completion_dir)
        / scenario
        / f"{county}_diagnostics_g{model_run_sha}.html"
        for scenario in CLAIMS_EAC_SCENARIOS
        for county in sorted(counties)
    ]
    missing_markers = [path for path in markers if not path.is_file()]
    if missing_markers:
        raise FileNotFoundError(
            f"Claims 2/3 model run is incomplete for {model_run_sha}: "
            f"{len(missing_markers)} completion markers missing; "
            f"first={missing_markers[0]}"
        )

    from helpers.plot_scenario_comparison_helper import (
        collect_eac_components_by_county,
    )

    frames = []
    for scenario in CLAIMS_EAC_SCENARIOS:
        frames.append(
            collect_eac_components_by_county(
                str(base_input_dir),
                HOUSING_TYPE,
                [scenario],
                sorted(counties),
                incentive="full_incentives",
                discount_rate=0.07,
                timestamp=timestamps[scenario],
                electricity_plan_preference=CLAIMS_ELECTRICITY_PLAN_PREFERENCE,
                electricity_variant="nem3",
            )
        )
    raw = pd.concat(frames, ignore_index=True)
    normalized = _validate_claims_eac_frame(raw, expected_counties=counties)
    destination = Path(source) if source is not None else claims_eac_source_path(model_run_sha)
    destination.parent.mkdir(parents=True, exist_ok=True)
    normalized[["scenario", "county_slug", *EAC_COMPONENT_COLUMNS]].to_csv(
        destination,
        index=False,
    )
    manifest = {
        "schema_version": CLAIMS_SOURCE_MANIFEST_SCHEMA_VERSION,
        "model_git_sha": model_run_sha,
        "scenario_run_timestamps": timestamps,
        "scenario_cases": CLAIMS_EAC_SCENARIOS,
        "expected_counties": sorted(counties),
        "completion_marker_count": len(markers),
        "housing_type": HOUSING_TYPE,
        "incentive_scenario": "full_incentives",
        "discount_rate": 0.07,
        "electricity_variant": "nem3",
        "electricity_plan_preference": list(CLAIMS_ELECTRICITY_PLAN_PREFERENCE),
        "source_csv": {
            "path": _manifest_display_path(destination),
            "sha256": _file_sha256(destination),
            "row_count": len(normalized),
        },
    }
    claims_eac_manifest_path(destination).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    collect_claims_eac_results(
        destination,
        expected_counties=counties,
        require_manifest=True,
    )
    return destination


def summarize_claims_eac(eac: pd.DataFrame) -> pd.DataFrame:
    """One county per row with the exact comparisons used by Claims 2 and 3."""

    required_cases = set(CLAIMS_EAC_SCENARIOS.values())
    if set(eac["case"]) != required_cases:
        raise ValueError(
            f"Claims EAC cases must be {sorted(required_cases)}; "
            f"found {sorted(set(eac['case']))}"
        )
    if eac.duplicated(["case", "county_slug"]).any():
        raise ValueError("Claims EAC input has duplicate case/county rows")
    wide = eac.pivot(index="county_slug", columns="case", values="total_eac")
    if wide.isna().any().any():
        raise ValueError("Claims EAC cases do not cover identical counties")
    wide = wide.reset_index()
    wide["gas_to_coopt_savings"] = (
        wide["gas_ice_reference"] - wide["cooptimized_electric"]
    )
    wide["gas_to_coopt_pct"] = (
        100.0 * wide["gas_to_coopt_savings"] / wide["gas_ice_reference"]
    )
    wide["fixed_to_coopt_savings"] = (
        wide["fixed_pv_electric"] - wide["cooptimized_electric"]
    )
    wide["fixed_to_coopt_pct"] = (
        100.0 * wide["fixed_to_coopt_savings"] / wide["fixed_pv_electric"]
    )
    return wide.sort_values("county_slug").reset_index(drop=True)


def sweep_cache_is_compatible(
    df: pd.DataFrame,
    max_battery_kwh: float,
    *,
    expected_points: Sequence[float],
    expected_columns: Optional[List[str]] = None,
) -> bool:
    """Whether cached results fully describe the requested sweep."""

    expected = normalize_battery_capex_points(expected_points)
    if "battery_capex_kwh" not in df.columns:
        return False
    actual = pd.to_numeric(df["battery_capex_kwh"], errors="coerce")

    return (
        list(df.columns) == (SWEEP_COLUMNS if expected_columns is None else expected_columns)
        and not df.empty
        and set(df["max_battery_kwh"].astype(float)) == {float(max_battery_kwh)}
        and not actual.isna().any()
        and not actual.duplicated().any()
        and sorted(actual.astype(float).tolist()) == expected
    )


def normalize_battery_capex_points(points: Sequence[float]) -> List[float]:
    """Validate, sort, and deduplicate an explicitly requested capex grid."""

    normalized = [float(point) for point in points]
    if not normalized:
        raise ValueError("Battery capex sweep points cannot be empty")
    if not all(math.isfinite(point) for point in normalized):
        raise ValueError("Battery capex sweep points must be finite")
    if any(point <= 0.0 for point in normalized):
        raise ValueError("Battery capex sweep points must be positive")
    return sorted(set(normalized))


def canonical_battery_capex_points(regime=None) -> List[float]:
    """Publication grid including the regime's exact modeled battery price."""

    return normalize_battery_capex_points(
        [*SWEEP_POINTS, live_prices(regime).batt_net_per_kwh]
    )


def select_market_observation(
    frame: pd.DataFrame,
    market_price: float,
) -> pd.Series:
    """Return the one solved row at ``market_price``, failing on ambiguity.

    Publication annotations use this primitive instead of interpolation or the
    nearest capex grid point. The strict checks prevent an old or incomplete
    cache from silently supplying a different modeled price.
    """

    missing = [column for column in SWEEP_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Market observation is missing columns: {missing}")
    numeric = frame[SWEEP_COLUMNS].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        raise ValueError("Market observation contains non-numeric or missing values")
    if not pd.notna(numeric).all().all() or not all(
        math.isfinite(value) for value in numeric.to_numpy().ravel()
    ):
        raise ValueError("Market observation contains non-finite values")
    matches = numeric[
        numeric["battery_capex_kwh"].map(
            lambda value: math.isclose(
                value,
                float(market_price),
                rel_tol=0.0,
                abs_tol=1e-9,
            )
        )
    ]
    if len(matches) != 1:
        raise ValueError(
            "Expected exactly one solved observation at battery capex "
            f"${market_price:.6f}/kWh; found {len(matches)}"
        )
    row = matches.iloc[0]
    if row["pv_kw"] < 0.0 or row["batt_kwh"] < 0.0:
        raise ValueError("Market observation cannot contain negative capacity")
    if int(row["solver_rounds"]) < 1:
        raise ValueError("Market observation must record at least one solver round")
    return row


def collect_market_price_observation(
    slug: str,
    *,
    regime=None,
    export_compensation_regime: (
        str | ExportCompensationRegime
    ) = ExportCompensationRegime.NBT_2026,
    scenario: str = DEFAULT_SCENARIO,
    max_battery_kwh: float = SWEEP_MODEL_SETTINGS.max_battery_kwh,
    cache: bool = True,
    force: bool = False,
    verbose: bool = True,
) -> pd.DataFrame:
    """Solve one exact market-price point using the full 8,760-hour chronology.

    The capex sensitivity curves remain the declared 12x24 approximation. This
    separate observation is the publication-grade check used for each market
    price annotation and Claim 1 headline statistic.
    """

    prices = live_prices(regime)
    export_regime = ExportCompensationRegime.parse(
        export_compensation_regime
    )
    market_price = prices.batt_net_per_kwh
    path = market_observation_csv_path(
        slug,
        prices.regime,
        export_regime,
    )
    if cache and not force and path.exists():
        cached = pd.read_csv(path)
        try:
            select_market_observation(cached, market_price)
        except ValueError:
            pass
        else:
            if (
                list(cached.columns) == MARKET_OBSERVATION_COLUMNS
                and len(cached) == 1
                and set(cached["max_battery_kwh"].astype(float))
                == {float(max_battery_kwh)}
                and set(cached["scenario"]) == {scenario}
                and set(cached["policy_regime"]) == {prices.regime}
                and set(cached["interval_count"].astype(int)) == {8760}
            ):
                return cached.reset_index(drop=True)

    frame = collect_battery_capex_sweep(
        slug,
        regime=regime,
        export_compensation_regime=export_regime,
        scenario=scenario,
        points=[market_price],
        max_battery_kwh=max_battery_kwh,
        fine=True,
        cache=False,
        force=True,
        verbose=verbose,
    )
    select_market_observation(frame, market_price)
    frame = frame.assign(
        scenario=scenario,
        policy_regime=prices.regime,
        interval_count=8760,
    )[MARKET_OBSERVATION_COLUMNS]
    if cache:
        SWEEP_DIR.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False)
    return frame.reset_index(drop=True)


def resolve_pv_capex(pv_capex_per_kw=None, regime=None) -> float:
    """The fixed PV $/kW a claim-figure sweep uses: an explicit override if given,
    otherwise the live net price for the regime (the model's sourced, tested
    price).

    This binds the figure data path to the model price by default. It is the
    regression guard for the 2026-07-27 finding that an old figure was drawn at
    an unlabeled $4,000/kW sensitivity-sweep endpoint instead of the real price.
    Sensitivity sweeps may still pass an explicit price; the default cannot
    silently drift to an arbitrary constant.
    """
    if pv_capex_per_kw is not None:
        return float(pv_capex_per_kw)
    return live_prices(regime).pv_net_per_kw


def collect_battery_capex_sweep(
    slug: str,
    *,
    regime=None,
    export_compensation_regime: (
        str | ExportCompensationRegime
    ) = ExportCompensationRegime.NBT_2026,
    scenario: str = DEFAULT_SCENARIO,
    points: Optional[Sequence[float]] = None,
    pv_capex_per_kw: Optional[float] = None,
    max_battery_kwh: float = SWEEP_MODEL_SETTINGS.max_battery_kwh,
    fine: bool = False,
    cache: bool = True,
    force: bool = False,
    verbose: bool = True,
) -> pd.DataFrame:
    """Optimal PV/battery sizing across a battery-capex grid for one county.

    Columns include battery_capex_kwh, pv_kw, batt_kwh, total_cost, coverage
    (PV annual generation / annual load), the battery-size domain bound, and
    solver diagnostics.

    Solar capex is fixed at the live net price for `regime` (default: current
    law), or `pv_capex_per_kw` if given. The default publication grid includes
    the regime's exact modeled net battery price. An explicit ``points``
    argument is treated as a deliberate custom grid and is only validated,
    sorted, and deduplicated. Results cache per county, export-compensation
    regime, and capital-policy regime. Sensitivity grids use weighted 12x24
    monthly-hour intervals by default. ``fine=True`` requests the full
    8,760-hour chronology.
    """
    prices = live_prices(regime)
    export_regime = ExportCompensationRegime.parse(
        export_compensation_regime
    )
    requested_points = (
        canonical_battery_capex_points(regime)
        if points is None
        else normalize_battery_capex_points(points)
    )
    resolution = "8760" if fine else "288"
    path = sweep_csv_path(
        slug,
        prices.regime,
        resolution,
        export_regime,
    )
    if cache and not force and path.exists():
        df = pd.read_csv(path)
        if sweep_cache_is_compatible(
            df,
            max_battery_kwh,
            expected_points=requested_points,
        ):
            return df.sort_values("battery_capex_kwh").reset_index(drop=True)

    from pipeline.steps.step9b_cooptimize_core import (
        _solve_lp,
        build_monthly_hourly_inputs,
    )

    c_pv = resolve_pv_capex(pv_capex_per_kw, regime)
    di = county_dispatch_inputs(
        slug,
        scenario,
        export_compensation_regime=export_regime,
    )
    inp = di.coopt_inputs()
    load, ypk = di.annual_load, di.yield_per_kw
    weights = None
    cycle_monthly = False
    if not fine:
        inp, weights = build_monthly_hourly_inputs(
            inp,
            year=SWEEP_MODEL_SETTINGS.billing_year,
        )
        cycle_monthly = True

    rows = []
    for cb in requested_points:
        t0 = time.time()
        r = _solve_lp(
            inp,
            allow_grid_charging=SWEEP_MODEL_SETTINGS.allow_grid_charging,
            allow_batt_export=SWEEP_MODEL_SETTINGS.allow_battery_export,
            c_pv_kw=c_pv,
            c_batt_kwh=float(cb),
            c_batt_kw=SWEEP_MODEL_SETTINGS.battery_power_cost_usd_per_kw,
            pv_life_yrs=SWEEP_MODEL_SETTINGS.pv_lifetime_years,
            batt_life_yrs=SWEEP_MODEL_SETTINGS.battery_lifetime_years,
            discount_rate=SWEEP_MODEL_SETTINGS.discount_rate,
            c_deg_per_kwh=(
                SWEEP_MODEL_SETTINGS.battery_degradation_cost_usd_per_kwh
            ),
            weights=weights,
            cycle_monthly=cycle_monthly,
            max_battery_kwh=max_battery_kwh,
            solver_backend=SWEEP_MODEL_SETTINGS.solver_backend,
        )
        rows.append({
            "battery_capex_kwh": cb, "pv_kw": r.pv_kw, "batt_kwh": r.batt_kwh,
            "total_cost": r.total_cost, "coverage": r.pv_kw * ypk / load,
            "max_battery_kwh": float(max_battery_kwh),
            "meter_binary_count": int(r.meter_binary_count),
            "solver_rounds": int(r.solver_rounds),
        })
        if verbose:
            print(f"  {slug:12} cb=${cb:>6}  PV={r.pv_kw:6.2f}  batt={r.batt_kwh:9.1f}"
                  f"  cover={r.pv_kw * ypk / load:.2f}  ({time.time() - t0:.0f}s)", flush=True)

    df = pd.DataFrame(rows, columns=SWEEP_COLUMNS)
    if cache:
        SWEEP_DIR.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
    return df
