"""Annual NBT research bills from validated meter flows and tariff rates."""

from dataclasses import dataclass
import math

from .accounting import AnnualCreditSettlement
from .models import EnergyFlows, TariffBundle
from .optimization import NBTOptimizationTerms


@dataclass(frozen=True)
class BillLedger:
    pool_names: tuple[str, ...]
    annual_import_kwh: float
    annual_export_kwh: float
    accounting: AnnualCreditSettlement[float]

    @property
    def annual_amount_due(self):
        return self.accounting.amount_due_usd

    @property
    def annual_credit_earned(self):
        return self.accounting.earned_credit_usd

    @property
    def annual_credit_applied(self):
        return self.accounting.applied_credit_usd

    @property
    def unused_credit(self):
        return self.accounting.unused_credit_usd

    @property
    def credit_saturation_ratio(self):
        """Fraction of earned credit that cannot offset this year's eligible charges."""
        return self.unused_credit / self.annual_credit_earned if self.annual_credit_earned else 0.0


def calculate_nbt_bill(flows: EnergyFlows, tariff: TariffBundle) -> BillLedger:
    """Settle base credits annually, within the research annual export cap.

    This is a representative-year cost model. It does not reconstruct monthly
    utility statements, ACC Plus, or credit transfers between modeled years.
    """
    frame = flows.validated_frame()
    terms = NBTOptimizationTerms.from_tariff(tariff, frame["timestamp"])
    imports = frame["import_kwh"].tolist()
    exports = frame["export_kwh"].tolist()
    accounting = terms.bill(imports, exports, [1.0] * len(frame))
    return BillLedger(
        terms.pool_names, math.fsum(imports), math.fsum(exports), accounting,
    )
