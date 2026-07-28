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

Scope correction (2026-07-17): the ITC was not an isolated problem. An audit of the appliance
layer found that EVERY federal credit it applies predates OBBBA and is labeled "through 2032":
IRC 25C on heat pumps and heat pump water heaters, and IRC 30D on vehicles, alongside the 25D
credit on solar and storage. See INCENTIVE_REGISTRY below for the full provenance table mapping
each credit to the call site that applies it, and WIRING_SEQUENCE for the agreed order of work.

Wiring status (2026-07): IRC 25D (solar, storage) reads its regime gating from this module
(federal_itc_fraction), and IRC 25C (heat pump, heat pump water heater) and IRC 30D (EV) do
too (federal_25c_credit, federal_30d_amount). This module is the single source of truth for
which federal incentives legally exist by regime; the appliance classes read the gating from
here and own only the gross costs.
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


# Federal energy efficient home improvement credit, IRC 25C. 30 percent of installed
# cost, capped at $2,000/yr for qualifying heat pumps and heat pump water heaters.
# Repealed by OBBBA for property placed in service after 2025-12-31.
FEDERAL_25C = DatedIncentive(
    name="federal_energy_efficient_home_improvement_credit",
    fraction=0.30,
    per_kwh=None,
    max_value=2000.0,
    valid_from="2023-01-01",
    valid_through="2025-12-31",
    applies_to="space_heating+water_heating",
    statute_or_program="IRC 25C",
    citation=(
        "Terminated by the One Big Beautiful Bill Act section 70505 for property placed "
        "in service after 2025-12-31. Pub. L. 119-21, 139 Stat. 72 (2025-07-04). "
        "IRS guidance on the OBBBA modification of sections 25C/25D/30D: "
        "https://www.irs.gov/newsroom/faqs-for-modification-of-sections-25c-25d-25e-30c-30d-45l-45w-and-179d-under-public-law-119-21-139-stat-72-july-4-2025-commonly-known-as-the-one-big-beautiful-bill-obbb"
    ),
    verification_status="verified",
    note=(
        "CAP IS COMBINED, NOT PER-APPLIANCE. The $2,000 is a single annual aggregate "
        "limit across heat pumps, heat pump water heaters, and biomass stoves/boilers "
        "(IRC 25C(b)(5)(A); IRS Energy Efficient Home Improvement Credit, "
        "https://www.irs.gov/credits-deductions/energy-efficient-home-improvement-credit). "
        "This model applies $2,000 to EACH appliance independently (electric_heating.py, "
        "electric_water_heating.py), which over-counts the credit for any scenario that "
        "installs both a heat pump AND a heat pump water heater in the same year. This "
        "does NOT affect current-law results (25C = 0 under POST_ITC_2026); it only "
        "inflates the ITC_2025 comparison. A correct fix is a bundle-level cap applied "
        "where appliances are summed (step14), left as a separate decision so it is not "
        "conflated with the OBBBA repeal delta."
    ),
)

# Federal clean vehicle credit, IRC 30D. Flat $7,500 for a qualifying new EV.
# Terminated by OBBBA for vehicles acquired after 2025-09-30, earlier than the
# 25C / 25D repeal date.
FEDERAL_30D = DatedIncentive(
    name="federal_clean_vehicle_credit",
    fraction=None,
    per_kwh=None,
    flat_amount=7500.0,
    valid_from="2023-01-01",
    valid_through="2025-09-30",
    applies_to=APPLIES_TO_VEHICLE,
    statute_or_program="IRC 30D",
    citation=(
        "Terminated by the One Big Beautiful Bill Act section 70502(a) for vehicles "
        "acquired after 2025-09-30 (amended IRC 30D(h), striking the prior 2032 date). "
        "Pub. L. 119-21, 139 Stat. 72 (2025-07-04). "
        "IRS guidance on the OBBBA modification of sections 25C/25D/30D: "
        "https://www.irs.gov/newsroom/faqs-for-modification-of-sections-25c-25d-25e-30c-30d-45l-45w-and-179d-under-public-law-119-21-139-stat-72-july-4-2025-commonly-known-as-the-one-big-beautiful-bill-obbb"
    ),
    verification_status="verified",
    note=(
        "Note the date: 30D dies 2025-09-30, three months BEFORE 25C and 25D. The "
        "regime enum is a two-value approximation and does not represent that gap. "
        "Harmless for a 2026-vintage analysis, where all three are gone."
    ),
)

# IRA Section 50122 High-Efficiency Electric Home Rebate (HEEHRA), $840 for a
# qualifying electric cooking appliance. NOT a tax credit and NOT repealed by OBBBA.
# State-administered, so availability is a program-status question, not a statutory one.
HEEHRA_COOKING = DatedIncentive(
    name="heehra_electric_cooking_rebate",
    fraction=None,
    per_kwh=None,
    flat_amount=840.0,
    valid_from="2022-08-16",
    valid_through=None,
    applies_to=APPLIES_TO_COOKING,
    statute_or_program="IRA Section 50122 (HEEHRA), administered by CEC in California",
    citation="TODO: confirm current California HEEHRA program status and remaining funding.",
    verification_status="needs_verification",
    note=(
        "The one federal incentive in the model that OBBBA did NOT repeal. Do not sweep "
        "it away with the tax credits. Its risk is program exhaustion, not statute: "
        "confirm whether CA's allocation is still open to new applicants, the same "
        "question that closed SGIP general-market."
    ),
)

# California utility EV rebate, modeled as a $3,000 average across PG&E, SCE, SDG&E.
CA_UTILITY_EV_REBATE = DatedIncentive(
    name="ca_utility_ev_rebate",
    fraction=None,
    per_kwh=None,
    flat_amount=3000.0,
    valid_from="2020-01-01",
    valid_through=None,
    applies_to=APPLIES_TO_VEHICLE,
    statute_or_program="California IOU electric vehicle rebates (PG&E / SCE / SDG&E average)",
    citation="TODO: confirm each IOU program is still open and re-derive the average.",
    verification_status="needs_verification",
    note=(
        "State/utility program, unaffected by OBBBA. Modeled as a single blended $3,000 "
        "rather than per-utility, which is a simplification worth stating if EV scenarios "
        "carry any weight in the paper."
    ),
)


# ---------------------------------------------------------------------------
# PROVENANCE REGISTRY
#
# Every federal or state incentive the appliance layer currently applies, mapped to
# the exact call site that applies it. Built 2026-07-17 during the post-ITC audit,
# which found that the ITC was not an isolated problem: the entire federal incentive
# stack in appliances/ predates OBBBA and is labeled "through 2032".
#
# Read this as the checklist for the wiring work. Order matters, see WIRING_SEQUENCE.
#
# WHY THIS MATTERS FOR THE PAPER'S CLAIMS:
#   Removing 25D makes solar and storage more expensive, which makes storage pencil
#   out even less well. That STRENGTHENS Claim 1 (storage does not pencil under NEM 3.0).
#   Removing 25C and 30D makes electrification more expensive relative to gas, which
#   pushes AGAINST Claim 2 (electrification beats gas in 46/47 counties). Claim 2 is
#   the claim at risk here. Claim 3 (co-optimized sizing beats naive sizing) is a
#   relative comparison at a common price and should be insensitive to all of this.
# ---------------------------------------------------------------------------
INCENTIVE_REGISTRY = (
    # (call site, encoded credit, DatedIncentive, live under DEFAULT_POLICY_REGIME?)
    ("appliances/solar_system.py:27",         "30%",             FEDERAL_ITC_25D,      False),
    ("appliances/battery_storage.py:27",      "30%",             FEDERAL_ITC_25D,      False),
    ("appliances/electric_heating.py:45",     "30%, cap $2,000", FEDERAL_25C,          False),
    ("appliances/electric_water_heating.py:46", "30%, cap $2,000", FEDERAL_25C,        False),
    ("appliances/electric_vehicle.py:37",     "$7,500",          FEDERAL_30D,          False),
    ("appliances/electric_cooking.py:29",     "$840",            HEEHRA_COOKING,       True),
    ("appliances/electric_vehicle.py:56",     "$3,000",          CA_UTILITY_EV_REBATE, True),
    # Documented for provenance, not applied at any call site.
    (None,                                    "$200/kWh",        SGIP_GENERAL_MARKET,  False),
)

# Agreed 2026-07-17. Wire in this order, one commit per step, so each result delta is
# separately attributable. Fixing all of them in one commit would move Claim 1 and
# Claim 2 simultaneously and lose the attribution.
WIRING_SEQUENCE = (
    "1. IRC 25D (solar + storage). Expected: storage pencils out even less. Strengthens Claim 1.",
    "2. IRC 25C and 30D (heat pump, water heater, EV). Expected: electrification gets more "
    "expensive vs gas. Tests Claim 2. Re-run the 47-county comparison and report the new count.",
    "3. Verify HEEHRA and the CA utility EV rebate as program-status questions. Neither was "
    "repealed by OBBBA, so neither belongs in steps 1 or 2.",
)


def federal_itc_fraction(regime: PolicyRegime = DEFAULT_POLICY_REGIME) -> float:
    """Federal ITC fraction of gross cost that legally applies under the given regime.

    Returns 0.0 post-ITC. The full/half/no IncentiveScenario multiplier is applied
    separately by the caller; this is the fraction that EXISTS, not the fraction captured.
    """
    if regime == PolicyRegime.ITC_2025:
        return FEDERAL_ITC_25D.fraction or 0.0
    return 0.0


def federal_25c_credit(regime: PolicyRegime = DEFAULT_POLICY_REGIME):
    """(fraction, per-appliance cap $) of the IRC 25C energy-efficient-home-
    improvement credit that legally applies under `regime`, or None if it does not.

    Terminated by OBBBA section 70505 after 2025-12-31, so None under current law.
    Mirrors federal_itc_fraction: this reports the credit that EXISTS, not the
    amount captured (the full/half/no IncentiveScenario multiplier is applied by
    the appliance). NOTE the cap is modeled here per appliance; the statute's
    $2,000 is a COMBINED annual cap across heat pumps + HPWH + biomass. See
    FEDERAL_25C.note. This only affects the ITC_2025 comparison (25C = 0 today)."""
    if regime == PolicyRegime.ITC_2025:
        return (FEDERAL_25C.fraction, FEDERAL_25C.max_value)
    return None


def federal_30d_amount(regime: PolicyRegime = DEFAULT_POLICY_REGIME):
    """Flat dollar IRC 30D clean-vehicle credit that legally applies under
    `regime`, or None if it does not.

    Terminated by OBBBA section 70502(a) for vehicles acquired after 2025-09-30,
    so None under current law."""
    if regime == PolicyRegime.ITC_2025:
        return FEDERAL_30D.flat_amount
    return None


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

    print(f"\n\nProvenance registry: federal and state incentives applied by appliances/")
    print(f"Default regime: {DEFAULT_POLICY_REGIME.value}\n")
    print(f"{'call site':44} {'encoded':16} {'statute/program':22} {'live?':6} check")
    print("-" * 110)
    for site, encoded, inc, live in INCENTIVE_REGISTRY:
        flag = "yes" if live else "NO"
        check = "" if inc.verification_status == "verified" else "VERIFY"
        print(f"{(site or '(not applied)'):44} {encoded:16} {inc.statute_or_program[:22]:22} {flag:6} {check}")

    print("\nWiring sequence (agreed 2026-07-17):")
    for step in WIRING_SEQUENCE:
        print(f"  {step}")
