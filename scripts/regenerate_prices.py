import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ["MPLBACKEND"] = "Agg"

from helpers.main_helpers import (  # noqa: E402
    central_counties,
    norcal_counties,
    socal_counties,
    slugify_county_name,
)
from tariffs import NBTScenario, TariffCatalog, resolve_county_service_assignment
from tariffs.calendar import full_year_hourly_index
from pipeline.steps.step9b_cooptimize_pv_battery import _write_price_diagnostics

OUTPUT_ROOT = REPO_ROOT / Path(
    "data/loadprofiles/baseline_coopt/single-family-detached"
)
MODELED_COUNTIES = tuple(
    slugify_county_name(county)
    for county in norcal_counties + central_counties + socal_counties
)


def regenerate_county_prices(
    county: str,
    *,
    output_root: Path = OUTPUT_ROOT,
    scenario: NBTScenario,
    tariff_catalog: TariffCatalog,
) -> None:
    output_dir = output_root / county
    if not output_dir.is_dir():
        raise FileNotFoundError(f"County output directory not found: {output_dir}")

    assignment = resolve_county_service_assignment(county)
    tariff = tariff_catalog.bundle(assignment.utility, scenario)
    timestamps = list(full_year_hourly_index(scenario.billing_year))

    import_prices = tariff.import_schedule.rates_for(timestamps)
    export_prices = [
        rate + tariff.acc_plus_rate
        for rate in tariff.export_schedule.rates_for(
            timestamps,
            component="total",
        )
    ]
    if len(import_prices) != 8760 or len(export_prices) != 8760:
        raise ValueError(
            f"{county} price diagnostics must contain 8,760 observations; "
            f"found {len(import_prices)} import and {len(export_prices)} export prices"
        )

    _write_price_diagnostics(
        str(output_dir),
        county,
        timestamps,
        import_prices,
        export_prices,
    )

    print(f"Utility: {assignment.utility.value}")
    print(f"Import source: {tariff.import_schedule.source_id}")
    print(
        "Export sources:",
        sorted(tariff.export_schedule.rows["source_id"].unique()),
    )
    print(f"Observations: {len(export_prices)}")
    print(f"Maximum export price: ${max(export_prices):.6f}/kWh")


def main() -> None:
    if len(MODELED_COUNTIES) != 47:
        raise ValueError(
            f"Expected 47 configured research counties; found {len(MODELED_COUNTIES)}"
        )
    if len(set(MODELED_COUNTIES)) != len(MODELED_COUNTIES):
        raise ValueError("Configured research counties contain duplicates")

    scenario = NBTScenario(
        billing_year=2026,
        nbt_vintage=2026,
        tariff_snapshot_date="2026-08-09",
        true_up_month="2026-08",
    )
    tariff_catalog = TariffCatalog()

    for county in MODELED_COUNTIES:
        print(f"\nRegenerating price diagnostics for {county}")
        regenerate_county_prices(
            county,
            scenario=scenario,
            tariff_catalog=tariff_catalog,
        )

    print(f"\nRegenerated price diagnostics for {len(MODELED_COUNTIES)} counties.")


if __name__ == "__main__":
    main()
