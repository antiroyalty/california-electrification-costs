"""Annual NBT tariff terms, credit settlement, and numeric billing."""

from dataclasses import dataclass
import math
from typing import Callable, Generic, Sequence, TypeVar

import pandas as pd

from .models import EnergyFlows, TariffBundle, Utility, require_annual_export_cap

Amount = TypeVar("Amount")


@dataclass(frozen=True)
class AnnualCreditSettlement(Generic[Amount]):
    """Annual dollar settlement for one or more eligible credit pools."""

    eligible_charge_usd: tuple[Amount, ...]
    earned_base_credit_usd: tuple[Amount, ...]
    remaining_charge_usd: tuple[Amount, ...]
    non_bypassable_charge_usd: Amount
    fixed_charge_usd: float

    @property
    def gross_charge_usd(self):
        return (
            sum(self.eligible_charge_usd)
            + self.non_bypassable_charge_usd
            + self.fixed_charge_usd
        )

    @property
    def earned_credit_usd(self):
        return sum(self.earned_base_credit_usd)

    @property
    def applied_credit_usd(self):
        return sum(self.eligible_charge_usd) - sum(self.remaining_charge_usd)

    @property
    def unused_credit_usd(self):
        return self.earned_credit_usd - self.applied_credit_usd

    @property
    def amount_due_usd(self):
        return (
            sum(self.remaining_charge_usd)
            + self.non_bypassable_charge_usd
            + self.fixed_charge_usd
        )


def settle_annual_credits(
    eligible_charge_usd: tuple[Amount, ...],
    earned_base_credit_usd: tuple[Amount, ...],
    non_bypassable_charge_usd: Amount,
    fixed_charge_usd: float,
    *,
    positive_part: Callable[[Amount], Amount] | None = None,
) -> AnnualCreditSettlement[Amount]:
    """Return fixed + NBC + sum(max(eligible charge - base credit, 0)).

    Numeric calls validate dollars and use ``max`` directly. Optimization
    supplies a positive-part expression, which the bill objective must minimize.
    The caller groups generation and delivery into the utility's eligible pools.
    """

    if not eligible_charge_usd or len(eligible_charge_usd) != len(
        earned_base_credit_usd
    ):
        raise ValueError(
            "Annual charges and credits must identify the same nonempty pools"
        )
    if positive_part is None:
        values = (
            *eligible_charge_usd,
            *earned_base_credit_usd,
            non_bypassable_charge_usd,
            fixed_charge_usd,
        )
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise ValueError(
                "Annual charges and credits must be finite and non-negative"
            )
        positive_part = lambda value: max(value, 0.0)
    return AnnualCreditSettlement(
        eligible_charge_usd,
        earned_base_credit_usd,
        tuple(
            positive_part(charge - credit)
            for charge, credit in zip(
                eligible_charge_usd,
                earned_base_credit_usd,
            )
        ),
        non_bypassable_charge_usd,
        fixed_charge_usd,
    )


@dataclass(frozen=True)
class NBTAnnualTerms:
    """Validated interval rates and annual charges for one NBT bill year."""

    billing_year: int
    billing_months: tuple[int, ...]
    eligible_rates_usd_per_kwh: tuple[tuple[float, ...], ...]
    base_export_rates_usd_per_kwh: tuple[tuple[float, ...], ...]
    nbc_rate_usd_per_kwh: float
    fixed_charges_usd: tuple[tuple[int, float], ...]
    utility: Utility

    def __post_init__(self):
        object.__setattr__(self, "utility", Utility.parse(self.utility))
        count = len(self.billing_months)
        if not count or any(month not in range(1, 13) for month in self.billing_months):
            raise ValueError("NBT billing months must be nonempty and within 1..12")
        if tuple(sorted(self.billing_months)) != self.billing_months:
            raise ValueError("NBT intervals must be in billing-month order")
        pool_count = len(self.pool(0, 0))
        for rows in (
            self.eligible_rates_usd_per_kwh,
            self.base_export_rates_usd_per_kwh,
        ):
            if len(rows) != count or any(len(row) != pool_count for row in rows):
                raise ValueError(
                    "NBT prices must match the intervals and utility credit pools"
                )
        months = tuple(sorted(set(self.billing_months)))
        if tuple(month for month, _ in self.fixed_charges_usd) != months:
            raise ValueError("NBT fixed charges must identify each billing month once")
        prices = [
            self.nbc_rate_usd_per_kwh,
            *(
                value
                for rows in (
                    self.eligible_rates_usd_per_kwh,
                    self.base_export_rates_usd_per_kwh,
                )
                for row in rows
                for value in row
            ),
            *(value for _, value in self.fixed_charges_usd),
        ]
        if any(not math.isfinite(value) or value < 0 for value in prices):
            raise ValueError("NBT prices must be finite and non-negative")

    def pool(self, generation, delivery):
        """Return the utility-specific eligible credit pools."""

        # SCE Schedule NBT 3.a.i/ii and 4.b combine bundled energy charges.
        if self.utility is Utility.SCE:
            return (generation + delivery,)
        return (generation, delivery)

    @property
    def pool_names(self):
        return (
            ("energy",)
            if self.utility is Utility.SCE
            else ("generation", "delivery")
        )

    @property
    def import_rates(self):
        return tuple(
            sum(row) + self.nbc_rate_usd_per_kwh
            for row in self.eligible_rates_usd_per_kwh
        )

    @property
    def export_rates(self):
        return tuple(sum(row) for row in self.base_export_rates_usd_per_kwh)

    @classmethod
    def from_tariff(cls, tariff: TariffBundle, timestamps):
        """Build annual terms from a tariff and ordered bill-year timestamps."""

        timestamps = pd.DatetimeIndex(timestamps)
        if (
            timestamps.empty
            or timestamps.hasnans
            or timestamps.has_duplicates
            or not timestamps.is_monotonic_increasing
        ):
            raise ValueError("NBT timestamps must be nonempty, unique, and ordered")
        if set(timestamps.year) != {tariff.scenario.billing_year}:
            raise ValueError("NBT timestamps must match the tariff billing year")
        pooled = tariff.utility is Utility.SCE

        def pools(generation, delivery):
            return (generation + delivery,) if pooled else (generation, delivery)

        schedule = tariff.import_schedule
        generation = schedule.rates_for(timestamps, component="generation")
        delivery = schedule.rates_for(timestamps, component="delivery")
        total = schedule.rates_for(timestamps)
        export_generation = tariff.export_schedule.rates_for(
            timestamps,
            component="generation",
        )
        export_delivery = tariff.export_schedule.rates_for(
            timestamps,
            component="delivery",
        )
        if any(
            len(values) != len(timestamps)
            for values in (
                generation,
                delivery,
                total,
                export_generation,
                export_delivery,
            )
        ):
            raise ValueError("NBT rate schedules must match the timestamp count")
        if any(not math.isfinite(value) or value < 0 for value in total):
            raise ValueError("NBT total import rates must be finite and non-negative")
        if any(
            abs(total_rate - generation_rate - delivery_rate) > 1e-6
            for total_rate, generation_rate, delivery_rate in zip(
                total,
                generation,
                delivery,
            )
        ):
            raise ValueError(
                "NBT import generation + delivery rates do not reconcile to total"
            )
        eligible = []
        exports = []
        for generation_rate, delivery_rate, export_generation_rate, export_delivery_rate in zip(
            generation,
            delivery,
            export_generation,
            export_delivery,
        ):
            # Validate components before pooling so negatives cannot cancel.
            generation_rate -= schedule.generation_non_offsettable_rate
            delivery_rate -= schedule.delivery_non_offsettable_rate
            if any(
                not math.isfinite(value) or value < 0
                for value in (
                    generation_rate,
                    delivery_rate,
                    export_generation_rate,
                    export_delivery_rate,
                )
            ):
                raise ValueError("NBT component rates must be finite and non-negative")
            eligible.append(pools(generation_rate, delivery_rate))
            exports.append(pools(export_generation_rate, export_delivery_rate))
        fixed = tuple(
            (
                int(month),
                sum(
                    schedule.daily_fixed_charge(day)
                    for day in timestamps[
                        timestamps.month == month
                    ].normalize().unique()
                ),
            )
            for month in sorted(set(timestamps.month))
        )
        return cls(
            billing_year=tariff.scenario.billing_year,
            billing_months=tuple(int(month) for month in timestamps.month),
            eligible_rates_usd_per_kwh=tuple(eligible),
            base_export_rates_usd_per_kwh=tuple(exports),
            nbc_rate_usd_per_kwh=(
                schedule.generation_non_offsettable_rate
                + schedule.delivery_non_offsettable_rate
            ),
            fixed_charges_usd=fixed,
            utility=tariff.utility,
        )

    def bill(
        self,
        imports: Sequence[Amount],
        exports: Sequence[Amount],
        weights: Sequence[float],
        *,
        positive_part=None,
        sum_amounts=math.fsum,
    ) -> AnnualCreditSettlement[Amount]:
        """Aggregate interval dollars, then settle the annual eligible pools.

        Symbolic callers provide a linear sum and positive-part expression.
        They must enforce the annual energy cap in their physical model. Numeric
        reporting validates the cap here, including representative-hour weights.
        """

        count = len(self.billing_months)
        if not (len(imports) == len(exports) == len(weights) == count):
            raise ValueError(
                "NBT meter flows and weights must match the tariff intervals"
            )
        if any(not math.isfinite(weight) or weight <= 0 for weight in weights):
            raise ValueError("NBT interval weights must be finite and positive")
        if positive_part is None:
            if any(
                not math.isfinite(value) or value < 0
                for value in (*imports, *exports)
            ):
                raise ValueError("NBT meter flows must be finite and non-negative")
            require_annual_export_cap(
                math.fsum(
                    weight * value for weight, value in zip(weights, imports)
                ),
                math.fsum(
                    weight * value for weight, value in zip(weights, exports)
                ),
            )
        eligible = tuple(
            sum_amounts(
                weights[hour]
                * imports[hour]
                * self.eligible_rates_usd_per_kwh[hour][pool_index]
                for hour in range(count)
            )
            for pool_index in range(len(self.pool_names))
        )
        credits = tuple(
            sum_amounts(
                weights[hour]
                * exports[hour]
                * self.base_export_rates_usd_per_kwh[hour][pool_index]
                for hour in range(count)
            )
            for pool_index in range(len(self.pool_names))
        )
        nbc = (
            sum_amounts(
                weight * value for weight, value in zip(weights, imports)
            )
            * self.nbc_rate_usd_per_kwh
        )
        return settle_annual_credits(
            eligible,
            credits,
            nbc,
            math.fsum(value for _, value in self.fixed_charges_usd),
            positive_part=positive_part,
        )


@dataclass(frozen=True)
class BillLedger:
    """Numeric annual NBT bill and its meter-energy totals."""

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
        """Return the share of earned credit above this year's eligible charges."""

        if not self.annual_credit_earned:
            return 0.0
        return self.unused_credit / self.annual_credit_earned


def calculate_nbt_bill(flows: EnergyFlows, tariff: TariffBundle) -> BillLedger:
    """Settle base credits annually, within the research annual export cap.

    This is a representative-year cost model. It does not reconstruct monthly
    utility statements, ACC Plus, or credit transfers between modeled years.
    """

    frame = flows.validated_frame()
    terms = NBTAnnualTerms.from_tariff(tariff, frame["timestamp"])
    imports = frame["import_kwh"].tolist()
    exports = frame["export_kwh"].tolist()
    accounting = terms.bill(imports, exports, [1.0] * len(frame))
    return BillLedger(
        terms.pool_names,
        math.fsum(imports),
        math.fsum(exports),
        accounting,
    )
