"""Federal purchase-credit rules used by the research's 2025/2026 comparisons.

Read the three records below for amounts, dates, eligibility, and sources.
This is a policy registry, not a household tax calculator. The records describe
legal rules; ``implementation_note`` identifies limits of the current code.
Credit capture and receipt timing are separate research assumptions.

Scope: homeowner-owned solar/storage, heat pumps, and purchased new vehicles.
State/local incentives, federally funded rebates, and other tax credits are
outside this registry. It does not reconstruct every historical rule change.
"""

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class FederalCredit:
    """One credit's sourced rules; dollar limits are distinct from percentages."""

    name: str
    statute_or_program: str
    applies_to: str
    valid_from: str
    valid_through: str
    date_basis: str
    eligible_costs: str
    eligibility: str
    claim_on_return_carryforward: bool
    tax_treatment: str
    source_urls: tuple[str, ...]
    implementation_note: str
    fraction: float | None = None
    annual_cap_usd: float | None = None
    maximum_credit_usd: float | None = None
    minimum_storage_capacity_kwh: float | None = None
    storage_valid_from: str | None = None
    dealer_transfer_valid_from: str | None = None
    verification_status: str = "verified"


FEDERAL_ITC_25D = FederalCredit(
    name="federal_residential_clean_energy_credit",
    statute_or_program="IRC 25D",
    applies_to="pv+storage",
    fraction=0.30,
    minimum_storage_capacity_kwh=3.0,
    valid_from="2022-01-01",
    storage_valid_from="2023-01-01",
    valid_through="2025-12-31",
    date_basis=(
        "Qualifying expenditure, generally when original installation is completed; "
        "advance payment alone does not establish eligibility."
    ),
    eligible_costs=(
        "New qualifying solar/storage equipment, installation labor, and related "
        "wiring. Exclude financing charges and ordinary roof work. Reduce the "
        "basis for applicable utility subsidies and purchase-price adjustments."
    ),
    eligibility=(
        "Qualifying property at the taxpayer's U.S. residence. Storage must meet "
        "minimum_storage_capacity_kwh. No general dollar cap for these technologies."
    ),
    claim_on_return_carryforward=True,
    tax_treatment=(
        "Nonrefundable. Unused eligible credit can carry forward. Full realization "
        "and the year of receipt must be declared rather than inferred from eligibility."
    ),
    source_urls=(
        "https://www.irs.gov/instructions/i5695",
        "https://www.irs.gov/credits-deductions/residential-clean-energy-credit",
        "https://www.irs.gov/pub/taxpros/fs-2025-01.pdf",
    ),
    implementation_note=(
        "The battery constructor enforces the capacity minimum. The optimizer "
        "still extends the eligible unit price below that minimum. Existing "
        "battery annualization repeats the same incentive treatment at replacement. "
        "Household tax liability, carryforward, and receipt timing are not modeled."
    ),
)


FEDERAL_25C = FederalCredit(
    name="federal_energy_efficient_home_improvement_credit",
    statute_or_program="IRC 25C",
    applies_to="space_heating+water_heating",
    fraction=0.30,
    annual_cap_usd=2000.0,
    valid_from="2023-01-01",
    valid_through="2025-12-31",
    date_basis="Qualifying property placed in service during the tax year.",
    eligible_costs=(
        "Qualifying heat pumps and heat-pump water heaters, including installation "
        "labor. Apply any required purchase-price adjustments before the credit."
    ),
    eligibility=(
        "Qualifying efficiency and manufacturer requirements at an existing "
        "U.S. home used as a residence. The annual cap is shared across heat pumps, "
        "heat-pump water heaters, and biomass stoves/boilers; it is not per appliance. "
        "Other section 25C categories are outside this research registry."
    ),
    claim_on_return_carryforward=False,
    tax_treatment=(
        "Nonrefundable. Unused credit cannot carry forward. The shared cap applies "
        "per taxpayer and tax year, not separately to each purchase."
    ),
    source_urls=(
        "https://www.irs.gov/instructions/i5695",
        "https://www.irs.gov/credits-deductions/energy-efficient-home-improvement-credit",
    ),
    implementation_note=(
        "Current appliance calculations apply the annual cap independently to "
        "space and water heating. A household calculation must enforce the shared "
        "cap and declared tax-credit realization before using the expanded comparison."
    ),
)


FEDERAL_30D = FederalCredit(
    name="federal_clean_vehicle_credit",
    statute_or_program="IRC 30D",
    applies_to="vehicle",
    maximum_credit_usd=7500.0,
    valid_from="2023-01-01",
    valid_through="2025-09-30",
    dealer_transfer_valid_from="2024-01-01",
    date_basis=(
        "Acquisition deadline. An eligible vehicle acquired by the deadline can "
        "be placed in service later; apply the IRS acquisition and reporting rules."
    ),
    eligible_costs=(
        "Purchase of a qualifying new clean vehicle. This is a maximum credit "
        "per vehicle, not a percentage of vehicle or home-charger cost."
    ),
    eligibility=(
        "Buyer income and vehicle MSRP limits, qualifying assembly and battery "
        "requirements, and an accepted seller report. The vehicle may qualify "
        "for less than maximum_credit_usd. Used vehicles and leases are outside scope."
    ),
    claim_on_return_carryforward=False,
    tax_treatment=(
        "A personal credit claimed on the return is limited by tax liability and "
        "cannot carry forward. An eligible dealer transfer can provide the full "
        "allowable amount even when tax liability is lower; buyer and vehicle "
        "eligibility still apply."
    ),
    source_urls=(
        "https://www.irs.gov/instructions/i8936",
        "https://www.irs.gov/credits-deductions/credits-for-new-clean-vehicles-purchased-in-2023-or-after",
        "https://www.irs.gov/newsroom/topic-h-frequently-asked-questions-about-transfer-of-new-clean-vehicle-credit-and-previously-owned-clean-vehicles-credit",
    ),
    implementation_note=(
        "The existing 2025 regime assumes the maximum credit without checking "
        "buyer/vehicle eligibility or acquisition date. It does not distinguish "
        "dealer transfer from claiming on a return. The 2026 regime grants no credit."
    ),
)


FEDERAL_CREDITS = MappingProxyType({
    "25D": FEDERAL_ITC_25D,
    "25C": FEDERAL_25C,
    "30D": FEDERAL_30D,
})
