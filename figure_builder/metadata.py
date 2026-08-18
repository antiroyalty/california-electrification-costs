"""Reproducibility manifest for publication-figure runs."""
from __future__ import annotations

import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from appliances.battery_storage import BatteryStorageAppliance
from appliances.electric_base import IncentiveScenario
from appliances.incentive_policy import PolicyRegime, federal_itc_fraction
from appliances.solar_system import SolarSystemAppliance
from figure_builder import REPO, git_short_sha
from figure_builder.datasets import (
    SWEEP_MODEL_SETTINGS,
    canonical_battery_capex_points,
)
from figure_builder.dispatch import (
    BASE_INPUT_DIR,
    CLAIM1_COUNTIES,
    DEFAULT_SCENARIO,
    HOUSING_TYPE,
    county_dispatch_input_paths,
)
from figure_builder.pricing import live_prices
from tariffs import (
    NBTScenario,
    TariffCatalog,
    Utility,
    resolve_county_service_assignment,
)

METADATA_SCHEMA_VERSION = 1


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPO.resolve()))
    except ValueError:
        return str(resolved)


def file_identity(path: str | Path) -> dict:
    """Return stable identity fields for one required run input or artifact."""

    resolved = Path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"Run metadata file not found: {resolved}")
    digest = hashlib.sha256()
    with resolved.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": _display_path(resolved),
        "sha256": digest.hexdigest(),
        "size_bytes": resolved.stat().st_size,
    }


def capital_cost_metadata() -> dict:
    """Gross source basis and regime-specific net prices used by the solver."""

    regimes = []
    for regime in (PolicyRegime.POST_ITC_2026, PolicyRegime.ITC_2025):
        prices = live_prices(regime)
        regimes.append(
            {
                "regime": regime.value,
                "federal_itc_fraction": federal_itc_fraction(regime),
                "pv_net_usd_per_kw": prices.pv_net_per_kw,
                "battery_net_usd_per_kwh": prices.batt_net_per_kwh,
                "exact_battery_sweep_observation_usd_per_kwh": (
                    prices.batt_net_per_kwh
                ),
                "battery_sweep_points_usd_per_kwh": (
                    canonical_battery_capex_points(regime)
                ),
            }
        )
    return {
        "incentive_scenario": IncentiveScenario.FULL_INCENTIVES.value,
        "gross_cost_basis": {
            "pv": {
                "value_usd_per_kw": SolarSystemAppliance.per_kw_cost(),
                "basis_year": SolarSystemAppliance.COST_BASIS_YEAR,
                "source_id": SolarSystemAppliance.COST_SOURCE_ID,
                "source_urls": [SolarSystemAppliance.COST_SOURCE_URL],
            },
            "battery": {
                "unit_cost_usd": BatteryStorageAppliance.BASE_UNIT_COST_USD,
                "unit_capacity_kwh": BatteryStorageAppliance.UNIT_CAPACITY_KWH,
                "value_usd_per_kwh": BatteryStorageAppliance.per_kwh_cost(),
                "basis_year": BatteryStorageAppliance.COST_BASIS_YEAR,
                "source_id": BatteryStorageAppliance.COST_SOURCE_ID,
                "source_urls": list(BatteryStorageAppliance.COST_SOURCE_URLS),
            },
        },
        "policy_regimes": regimes,
    }


def tariff_metadata() -> dict:
    """Source identities for every tariff schedule used by the case studies."""

    scenario = NBTScenario()
    catalog = TariffCatalog()
    utilities = []
    for utility in Utility:
        bundle = catalog.bundle(utility, scenario)
        export_source_ids = sorted(
            str(value)
            for value in bundle.export_schedule.rows["source_id"].dropna().unique()
        )
        if not export_source_ids:
            raise ValueError(f"{utility.value} export schedule has no source_id")
        utilities.append(
            {
                "utility": utility.value,
                "import": {
                    "plan_name": bundle.import_schedule.plan_name,
                    "source_id": bundle.import_schedule.source_id,
                    "effective_date": bundle.import_schedule.effective_date,
                    "rate_unit": bundle.import_schedule.plan_details["rate_unit"],
                    "fixed_charge_unit": bundle.import_schedule.plan_details[
                        "fixed_charge_unit"
                    ],
                },
                "export": {
                    "source_ids": export_source_ids,
                    "rate_unit": "USD/kWh",
                },
                "acc_plus": {
                    "included": scenario.include_acc_plus,
                    "rate_usd_per_kwh": bundle.acc_plus_rate,
                    "rate_unit": "USD/kWh",
                    "source_id": bundle.acc_plus_source_id,
                },
            }
        )
    return {
        "scenario": {
            "billing_year": scenario.billing_year,
            "nbt_vintage": scenario.nbt_vintage,
            "service_type": scenario.service_type.value,
            "customer_segment": scenario.customer_segment.value,
            "tariff_snapshot_date": scenario.tariff_snapshot_date,
        },
        "source_manifests": [
            "data/tariffs/import_source_manifest.json",
            "data/tariffs/source_manifest.json",
            "data/tariffs/acc_plus_rates.csv",
        ],
        "utilities": utilities,
        "annual_true_up": {
            "used_by_sweep": False,
            "reason": (
                "The sizing sweep uses hourly import and NBT export prices; "
                "annual NSC settlement is not part of this objective."
            ),
        },
    }


def optimization_metadata(*, fine: bool) -> dict:
    """The actual fixed settings passed to the sweep co-optimization."""

    from pipeline.steps.step9b_cooptimize_core import (
        HIGHS_MIP_RELATIVE_GAP,
        SOLVER_OUTPUT_ABSOLUTE_TOLERANCE,
        _RTE,
        _SOC_MAX_FR,
        _SOC_MIN_FR,
    )

    settings = SWEEP_MODEL_SETTINGS
    return {
        "billing_year": settings.billing_year,
        "temporal_resolution": {
            "name": "full_8760_hour" if fine else "weighted_12x24_monthly_hour",
            "interval_count": 8760 if fine else 288,
            "soc_cycle": "annual" if fine else "monthly",
        },
        "market_price_observations": {
            "name": "full_8760_hour",
            "interval_count": 8760,
            "soc_cycle": "annual",
            "points_per_county_and_regime": 1,
            "policy_regimes": [PolicyRegime.POST_ITC_2026.value],
            "purpose": (
                "Exact current-law solved observations for publication "
                "market-price annotations; the 2025 ITC comparison remains "
                "an explicitly labeled 12x24 sensitivity."
            ),
        },
        "solver": {
            "backend": settings.solver_backend,
            "mip_relative_gap": HIGHS_MIP_RELATIVE_GAP,
            "output_absolute_tolerance": SOLVER_OUTPUT_ABSOLUTE_TOLERANCE,
        },
        "sizing_domain": {
            "max_battery_kwh": settings.max_battery_kwh,
            "max_pv_to_annual_load_ratio": settings.max_pv_to_annual_load_ratio,
            "battery_power_limit_c_rate": 1.0,
        },
        "battery_physics": {
            "round_trip_efficiency": _RTE,
            "minimum_soc_fraction": _SOC_MIN_FR,
            "maximum_soc_fraction": _SOC_MAX_FR,
            "allow_grid_charging": settings.allow_grid_charging,
            "allow_battery_export": settings.allow_battery_export,
        },
        "financial_assumptions": {
            "discount_rate": settings.discount_rate,
            "pv_lifetime_years": settings.pv_lifetime_years,
            "battery_lifetime_years": settings.battery_lifetime_years,
            "battery_replacement_within_pv_horizon": True,
            "battery_power_cost_usd_per_kw": (
                settings.battery_power_cost_usd_per_kw
            ),
            "battery_degradation_cost_usd_per_kwh": (
                settings.battery_degradation_cost_usd_per_kwh
            ),
        },
    }


def software_metadata() -> dict:
    """Versions that can affect optimization results or rendered figures."""

    import matplotlib
    import numpy
    import pandas
    import pulp
    import scipy

    return {
        "python": platform.python_version(),
        "numpy": numpy.__version__,
        "pandas": pandas.__version__,
        "scipy": scipy.__version__,
        "pulp": pulp.__version__,
        "matplotlib": matplotlib.__version__,
    }


def _deduplicated_file_identities(paths: Iterable[str | Path]) -> list[dict]:
    seen = set()
    identities = []
    for value in paths:
        path = Path(value).resolve()
        if path in seen:
            continue
        seen.add(path)
        identities.append(file_identity(path))
    return identities


def build_run_metadata(
    artifacts: Sequence[str | Path],
    *,
    fine: bool,
    force: bool,
    requested_counties: Sequence[str] | None = None,
    generated_at: datetime | None = None,
    scenario: str = DEFAULT_SCENARIO,
    base_input_dir: str | Path = BASE_INPUT_DIR,
) -> dict:
    """Build a complete, JSON-serializable receipt for one figure run."""

    timestamp = generated_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")

    inputs = []
    counties = []
    for slug, label, declared_utility in CLAIM1_COUNTIES:
        assignment = resolve_county_service_assignment(slug)
        if assignment.utility.value != declared_utility:
            raise ValueError(
                f"Case-study utility mismatch for {slug}: declared "
                f"{declared_utility}, resolved {assignment.utility.value}"
            )
        weather_path, load_path = county_dispatch_input_paths(
            slug,
            scenario=scenario,
            base=base_input_dir,
        )
        weather = file_identity(weather_path)
        weather["role"] = "weather_tmy"
        weather["county_slug"] = slug
        load = file_identity(load_path)
        load["role"] = "combined_load_profile"
        load["county_slug"] = slug
        inputs.extend([weather, load])
        counties.append(
            {
                "county_slug": slug,
                "county_name": label,
                "utility": assignment.utility.value,
                "utility_assignment_method": assignment.assignment_method,
            }
        )

    return {
        "schema_version": METADATA_SCHEMA_VERSION,
        "run": {
            "generated_at_utc": timestamp.astimezone(timezone.utc).isoformat(),
            "git_sha": git_short_sha(),
            "command": "python3 -m figure_builder all",
            "force": bool(force),
            "fine": bool(fine),
            "requested_counties": (
                list(requested_counties) if requested_counties is not None else None
            ),
            "scenario": scenario,
            "housing_type": HOUSING_TYPE,
            "counties": counties,
        },
        "optimization": optimization_metadata(fine=fine),
        "capital_costs": capital_cost_metadata(),
        "tariffs": tariff_metadata(),
        "inputs": inputs,
        "software": software_metadata(),
        "artifacts": _deduplicated_file_identities(artifacts),
    }


def write_run_metadata(path: str | Path, metadata: dict) -> Path:
    """Write a deterministic, human-readable run manifest."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination
