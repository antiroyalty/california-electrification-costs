"""
Dated, cited source of truth for which residential energy incentives apply, by policy regime.

This module exists to fix a real inconsistency found 2026-07: the capital-cost model applied
a 30 percent federal ITC unconditionally ("through 2032"), while the plotting layer already
assumed the ITC had expired. The federal residential clean energy credit (IRC section 25D) was
in fact repealed for expenditures made after 2025-12-31 by the One Big Beautiful Bill Act
(Pub. L. 119-21, 2025-07-04). A 2026-vintage analysis therefore has no federal ITC on owned
residential solar or storage.

Design (approved 2026-07): the POLICY REGIME decides which incentives legally exist. The separate
IncentiveScenario (full / half / no) keeps its existing job of deciding how much of the AVAILABLE
incentive a given decision-maker actually captures. The two axes are orthogonal. Under the default
POST_ITC_2026 regime there is no federal ITC, so for PV and storage full / half / no all collapse to
gross cost. This module owns the regime-to-incentive mapping. Gross costs still live in the appliance
classes; this module does not duplicate them.

Nothing is wired to this module yet. It is the single place the LP sizing price and every plot
reference label should read from once integration begins.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class PolicyRegime(Enum):
    """Which incentive regime is in force for the modeled installation year."""

    # Federal residential clean energy credit (IRC 25D), 30 percent, in effect for
    # installations completed on or before 2025-12-31.
    ITC_2025 = "itc_2025"

    # IRC 25D repealed for expenditures after 2025-12-31 by OBBBA (Pub. L. 119-21).
    # No federal residential ITC on owned solar or storage. This is current law.
    POST_ITC_2026 = "post_itc_2026"


# The headline regime for a paper published in 2026. The ITC era is available as an
# explicit comparison regime, not the default.
DEFAULT_POLICY_REGIME = PolicyRegime.POST_ITC_2026


@dataclass(frozen=True)
class DatedIncentive:
    """A single incentive with a validity window and a citation."""

    name: str
    fraction: Optional[float]  # of gross cost, for percentage incentives
    per_kwh: Optional[float]   # dollars per kWh of storage, for fixed-rate rebates
    valid_from: str            # ISO date
    valid_through: Optional[str]  # ISO date, or None if open-ended
    applies_to: str            # see APPLIES_TO_* below
    statute_or_program: str
    citation: str
    note: str = ""
    flat_amount: Optional[float] = None  # flat dollar credit, e.g. 30D's $7,500
    max_value: Optional[float] = None    # cap on a percentage credit, e.g. 25C's $2,000
    verification_status: str = "verified"  # "verified" | "needs_verification"


# Values for DatedIncentive.applies_to. These name the modeled appliance class,
# not the tax-code category, so the registry below can be read against the code.
APPLIES_TO_PV = "pv"
APPLIES_TO_STORAGE = "storage"
APPLIES_TO_PV_STORAGE = "pv+storage"
APPLIES_TO_SPACE_HEATING = "space_heating"
APPLIES_TO_WATER_HEATING = "water_heating"
APPLIES_TO_COOKING = "cooking"
APPLIES_TO_VEHICLE = "vehicle"


# ---------------------------------------------------------------------------
# Worked derivation of the net sizing prices this module implies.
# Gross costs are NOT stored here; they come from the appliance classes, which
# derive them from unit economics:
#   PV gross     = $3.30/W x 1000 W/kW                = $3,300.00 /kW
#                  (SolarSystemAppliance.per_kw_cost, CPUC 2023 $/W)
#   Battery gross = $18,258 per unit / 12.5 kWh per unit = $1,460.64 /kWh
#                  (BatteryStorageAppliance.per_kwh_cost, NREL ATB via CEC-200-2024-011)
#
# Net = gross x (1 - federal_itc_fraction(regime)):
#   itc_2025      (ITC 0.30):  PV  3,300 x 0.70 = $2,310.00 /kW
#                              Batt 1,460.64 x 0.70 = $1,022.448 /kWh  (shown as $1,022.45)
#   post_itc_2026 (ITC 0.00):  PV  3,300 x 1.00 = $3,300.00 /kW
#                              Batt 1,460.64 x 1.00 = $1,460.64 /kWh
#
# The itc_2025 values reproduce the appliance classes' own get_net_cost(FULL_INCENTIVES)
# to the penny, since both encode a flat 30 percent of gross. Verify with:
#   python3 appliances/incentive_policy.py
# ---------------------------------------------------------------------------
# Federal residential clean energy credit, IRC 25D, 30 percent of installed cost.
# Repealed for expenditures after 2025-12-31.
FEDERAL_ITC_25D = DatedIncentive(
    name="federal_residential_clean_energy_credit",
    fraction=0.30,
    per_kwh=None,
    valid_from="2022-01-01",
    valid_through="2025-12-31", # expenditures made on or before this date / last_eligible_expenditure_date
    applies_to="pv+storage",
    statute_or_program="IRC 25D",
    citation=(
        "Repealed for expenditures made after 2025-12-31 by the One Big Beautiful Bill Act, "
        "Pub. L. 119-21, 139 Stat. 72 (2025-07-04). "
        "Congressional Research Service, IN12611: https://www.congress.gov/crs-product/IN12611"
    ),
)

# California Self-Generation Incentive Program, general-market storage rebate.
# Documented for provenance. NOT applied in any headline regime: the general-market,
# equity, and equity-resilience budgets were closed to new applicants as of 2026-04.
# Kept here so a reviewer can see it was considered, and so a future sensitivity can turn it on.
SGIP_GENERAL_MARKET = DatedIncentive(
    name="ca_sgip_general_market_storage",
    fraction=None,
    per_kwh=200.0,  # approximate general-market rate before budget-step decline, representative early General Market residential incentive; not universal
    valid_from="2020-01-01",
    valid_through=None,
    applies_to="storage",
    statute_or_program="CA Self-Generation Incentive Program (CPUC)",
    citation="CPUC SGIP. General-market budget closed to new applicants as of 2026-04.",
    note="Not applied in any headline regime (program closed). Available for a sensitivity only.",
)


def federal_itc_fraction(regime: PolicyRegime = DEFAULT_POLICY_REGIME) -> float:
    """Federal ITC fraction of gross cost that legally applies under the given regime.

    Returns 0.0 post-ITC. The full/half/no IncentiveScenario multiplier is applied
    separately by the caller; this is the fraction that EXISTS, not the fraction captured.
    """
    if regime == PolicyRegime.ITC_2025:
        return FEDERAL_ITC_25D.fraction or 0.0
    return 0.0


def regime_summary(regime: PolicyRegime = DEFAULT_POLICY_REGIME) -> str:
    """One-line human description for plot labels and captions."""
    if regime == PolicyRegime.ITC_2025:
        return "ITC era (30% federal ITC, installs completed by 2025-12-31)"
    return "2026 current law (no federal ITC; IRC 25D repealed by OBBBA)"


if __name__ == "__main__":
    # Demonstration only. Reads gross costs from the appliance classes and shows the
    # net sizing price each regime implies, so the numbers can be checked before wiring.
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from appliances.solar_system import SolarSystemAppliance
    from appliances.battery_storage import BatteryStorageAppliance

    pv_gross = SolarSystemAppliance.per_kw_cost()
    batt_gross = BatteryStorageAppliance.per_kwh_cost()
    print(f"Gross (sourced, unchanged): PV ${pv_gross:,.2f}/kW   Battery ${batt_gross:,.2f}/kWh")
    print(f"Default regime: {DEFAULT_POLICY_REGIME.value}\n")
    print(f"{'regime':16} {'PV net $/kW':>14} {'Batt net $/kWh':>16}   description")
    for r in PolicyRegime:
        f = federal_itc_fraction(r)
        pv_net = pv_gross * (1 - f)
        batt_net = batt_gross * (1 - f)
        marker = "  <-- default" if r == DEFAULT_POLICY_REGIME else ""
        print(f"{r.value:16} {pv_net:>14,.2f} {batt_net:>16,.2f}   {regime_summary(r)}{marker}")
