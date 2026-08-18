"""Explicit policy cases used by the NBT versus NEM 2 comparison."""
from __future__ import annotations

from dataclasses import dataclass

from appliances.incentive_policy import PolicyRegime
from tariffs import ExportCompensationRegime


@dataclass(frozen=True)
class PolicyCase:
    """One export-compensation and capital-policy combination."""

    export_compensation_regime: ExportCompensationRegime
    capital_policy_regime: PolicyRegime

    @property
    def case_id(self) -> str:
        return (
            f"{self.export_compensation_regime.value}__"
            f"{self.capital_policy_regime.value}"
        )


POLICY_CASES = tuple(
    PolicyCase(export_regime, capital_regime)
    for export_regime in ExportCompensationRegime
    for capital_regime in (
        PolicyRegime.POST_ITC_2026,
        PolicyRegime.ITC_2025,
    )
)

# NBT with the lower ITC-era capital prices remains a weighted 12x24
# sensitivity. Its corrected Southern California full-year MILPs exceed the
# bounded publication workflow. Both NEM 2 market-price cases solve with one
# annual settlement binary and retain the full 8,760-hour chronology.
FULL_HOURLY_POLICY_CASES = tuple(
    case
    for case in POLICY_CASES
    if not (
        case.export_compensation_regime is ExportCompensationRegime.NBT_2026
        and case.capital_policy_regime is PolicyRegime.ITC_2025
    )
)


def policy_case(
    export_compensation_regime: str | ExportCompensationRegime,
    capital_policy_regime: PolicyRegime,
) -> PolicyCase:
    """Resolve one declared comparison case and reject unsupported pairs."""

    candidate = PolicyCase(
        ExportCompensationRegime.parse(export_compensation_regime),
        capital_policy_regime,
    )
    if candidate not in POLICY_CASES:
        raise ValueError(f"Unsupported policy case {candidate.case_id}")
    return candidate
