"""Source-linked NBT prices and shared accounting for meter-flow decisions.

Hourly energy becomes monthly dollars here. Credit application is defined only
in accounting_equations, which numeric billing also uses. Ending banks retain
their balances and have zero terminal value in the representative-year objective.
"""

from dataclasses import dataclass
import math
from typing import Generic, Sequence

import pandas as pd

from .accounting import PooledAmount
from .accounting_equations import (
    AccountingArithmetic, Amount, AnnualValues, MonthlyValues, NumericArithmetic,
    annual_accounting, monthly_accounting,
)
from .models import TariffBundle
from .true_up import (
    AverageRetailExportCompensationRate,
    AverageRetailExportCompensationSchedule,
    NetSurplusCompensationRate,
    NetSurplusCompensationSchedule,
    TrueUpPolicy,
)


@dataclass(frozen=True)
class NBTBillValues(Generic[Amount]):
    months: tuple[MonthlyValues[Amount], ...]
    annual: AnnualValues[Amount]
    gross_charge_usd: Amount
    earned_credit_usd: Amount
    net_surplus_kwh: Amount
    amount_due_usd: Amount


@dataclass(frozen=True)
class NBTOptimizationTerms:
    billing_year: int
    true_up_month: str
    billing_months: tuple[int, ...]
    eligible_rates_usd_per_kwh: tuple[tuple[float, ...], ...]
    base_export_rates_usd_per_kwh: tuple[tuple[float, ...], ...]
    nbc_rate_usd_per_kwh: float
    bonus_rate_usd_per_kwh: float
    fixed_charges_usd: tuple[tuple[int, float], ...]
    policy: TrueUpPolicy
    adjustment_rate: AverageRetailExportCompensationRate | None
    nsc_rate: NetSurplusCompensationRate

    def __post_init__(self):
        if not isinstance(self.policy, TrueUpPolicy):
            raise TypeError("NBT optimization requires a TrueUpPolicy")
        if not isinstance(self.nsc_rate, NetSurplusCompensationRate):
            raise TypeError("NBT optimization requires a source-linked NSC rate")
        if self.adjustment_rate is not None and not isinstance(
            self.adjustment_rate, AverageRetailExportCompensationRate
        ):
            raise TypeError("NBT adjustment must be a source-linked rate or explicitly missing")
        count = len(self.billing_months)
        if not count or any(m not in range(1, 13) for m in self.billing_months):
            raise ValueError("NBT billing months must be nonempty and within 1..12")
        if tuple(sorted(self.billing_months)) != self.billing_months:
            raise ValueError("NBT intervals must be in billing-month order")
        pools = len(self.pool(0, 0))
        for rows in (self.eligible_rates_usd_per_kwh, self.base_export_rates_usd_per_kwh):
            if len(rows) != count or any(len(row) != pools for row in rows):
                raise ValueError("NBT prices must match the intervals and utility credit pools")
        months = tuple(sorted(set(self.billing_months)))
        if tuple(m for m, _ in self.fixed_charges_usd) != months:
            raise ValueError("NBT fixed charges must identify each billing month once")
        prices = [
            self.nbc_rate_usd_per_kwh, self.bonus_rate_usd_per_kwh,
            *(v for rows in (self.eligible_rates_usd_per_kwh, self.base_export_rates_usd_per_kwh)
              for row in rows for v in row),
            *(v for _, v in self.fixed_charges_usd),
        ]
        if any(not math.isfinite(v) or v < 0 for v in prices):
            raise ValueError("NBT prices must be finite and non-negative")
        for rate in (self.adjustment_rate, self.nsc_rate):
            if rate is not None and (
                rate.utility is not self.policy.utility or rate.true_up_month != self.true_up_month
            ):
                raise ValueError("NBT settlement rates must match the utility and true-up month")

    def pool(self, generation, delivery):
        # Resolve restrictions through the same policy that numeric billing uses.
        if isinstance(self.policy.energy_amounts(0, 0), PooledAmount):
            return (generation + delivery,)
        return (generation, delivery)

    @property
    def import_rates(self):
        return tuple(
            sum(row) + self.nbc_rate_usd_per_kwh for row in self.eligible_rates_usd_per_kwh
        )

    @property
    def export_rates(self):
        return tuple(
            sum(row) + self.bonus_rate_usd_per_kwh for row in self.base_export_rates_usd_per_kwh
        )

    @classmethod
    def from_tariff(
        cls, tariff: TariffBundle, timestamps, *, adjustment_schedule=None, nsc_schedule=None,
    ):
        timestamps = pd.DatetimeIndex(timestamps)
        if (timestamps.empty or timestamps.hasnans or timestamps.has_duplicates
                or not timestamps.is_monotonic_increasing):
            raise ValueError("NBT timestamps must be nonempty, unique, and ordered")
        if set(timestamps.year) != {tariff.scenario.billing_year}:
            raise ValueError("NBT timestamps must match the tariff billing year")
        policy = TrueUpPolicy.for_utility(tariff.utility)
        pooled = isinstance(policy.energy_amounts(0, 0), PooledAmount)

        def pools(generation, delivery):
            return (generation + delivery,) if pooled else (generation, delivery)

        schedule = tariff.import_schedule
        generation = schedule.rates_for(timestamps, component="generation")
        delivery = schedule.rates_for(timestamps, component="delivery")
        total = schedule.rates_for(timestamps)
        export_generation = tariff.export_schedule.rates_for(timestamps, component="generation")
        export_delivery = tariff.export_schedule.rates_for(timestamps, component="delivery")
        if any(len(v) != len(timestamps) for v in (
            generation, delivery, total, export_generation, export_delivery
        )):
            raise ValueError("NBT rate schedules must match the timestamp count")
        if any(not math.isfinite(v) or v < 0 for v in total):
            raise ValueError("NBT total import rates must be finite and non-negative")
        if any(abs(t - g - d) > 1e-6 for t, g, d in zip(total, generation, delivery)):
            raise ValueError("NBT import generation + delivery rates do not reconcile to total")
        eligible = []
        exports = []
        for g, d, eg, ed in zip(generation, delivery, export_generation, export_delivery):
            # Validate components before pooling so negatives cannot cancel.
            g -= schedule.generation_non_offsettable_rate
            d -= schedule.delivery_non_offsettable_rate
            policy.energy_amounts(g, d)
            policy.energy_amounts(eg, ed)
            eligible.append(pools(g, d))
            exports.append(pools(eg, ed))
        fixed = tuple(
            (int(m), sum(schedule.daily_fixed_charge(day) for day in
                         timestamps[timestamps.month == m].normalize().unique()))
            for m in sorted(set(timestamps.month))
        )
        adjustments = adjustment_schedule or AverageRetailExportCompensationSchedule.from_csv()
        nsc = nsc_schedule or NetSurplusCompensationSchedule.from_csv()
        try:
            adjustment = adjustments.resolve(tariff.utility, tariff.scenario.true_up_month)
        except KeyError:
            # A validated schedule has no matching row. Keep this absence explicit.
            # The optimizer may certify a no-surplus solution using a lower bound.
            adjustment = None
        return cls(
            billing_year=tariff.scenario.billing_year,
            true_up_month=tariff.scenario.true_up_month,
            billing_months=tuple(int(m) for m in timestamps.month),
            eligible_rates_usd_per_kwh=tuple(eligible),
            base_export_rates_usd_per_kwh=tuple(exports),
            nbc_rate_usd_per_kwh=(schedule.generation_non_offsettable_rate
                                 + schedule.delivery_non_offsettable_rate),
            bonus_rate_usd_per_kwh=tariff.acc_plus_rate,
            fixed_charges_usd=fixed, policy=policy, adjustment_rate=adjustment,
            nsc_rate=nsc.resolve(tariff.utility, tariff.scenario.true_up_month),
        )

    def bill(
        self, imports: Sequence[Amount], exports: Sequence[Amount], weights: Sequence[float],
        arithmetic: AccountingArithmetic[Amount], *, missing_rate_lower_bound: bool = False,
    ) -> NBTBillValues[Amount]:
        """Build the annual bill from physical flows using shared credit equations.

        Omitting a nonnegative surplus adjustment gives a lower bound on cost.
        This bound is exact when the solution has no annual net surplus. Numeric
        evaluation rejects positive surplus with a missing rate before reporting.
        """
        count = len(self.billing_months)
        if not (len(imports) == len(exports) == len(weights) == count):
            raise ValueError("NBT meter flows and weights must match the tariff intervals")
        if any(not math.isfinite(w) or w <= 0 for w in weights):
            raise ValueError("NBT interval weights must be finite and positive")
        if isinstance(arithmetic, NumericArithmetic):
            if missing_rate_lower_bound:
                raise ValueError("A lower-bound bill cannot be reported as numeric accounting")
            if any(not math.isfinite(v) or v < 0 for v in (*imports, *exports)):
                raise ValueError("NBT meter flows must be finite and non-negative")
        zero = self.pool(0.0, 0.0)
        balance, bonus_balance = zero, 0.0
        rows = []
        gross = 0.0
        earned = 0.0
        for month, fixed in self.fixed_charges_usd:
            hours = [h for h, m in enumerate(self.billing_months) if m == month]
            eligible = tuple(sum(
                weights[h] * imports[h] * self.eligible_rates_usd_per_kwh[h][i]
                for h in hours
            ) for i in range(len(zero)))
            base = tuple(sum(
                weights[h] * exports[h] * self.base_export_rates_usd_per_kwh[h][i]
                for h in hours
            ) for i in range(len(zero)))
            nbc = sum(weights[h] * imports[h] for h in hours) * self.nbc_rate_usd_per_kwh
            # Keep an excluded bonus numeric. A symbolic zero would create unnecessary
            # bonus-bank variables and nonlinear proportional allocation constraints.
            bonus = 0.0
            if self.bonus_rate_usd_per_kwh > 0:
                bonus = sum(weights[h] * exports[h] for h in hours) * self.bonus_rate_usd_per_kwh
            row = monthly_accounting(
                eligible=eligible, nbc=nbc, fixed=fixed,
                opening_base=balance, opening_bonus=bonus_balance,
                earned_base=base, earned_bonus=bonus, arithmetic=arithmetic,
            )
            rows.append(row)
            balance, bonus_balance = row.closing_base, row.closing_bonus
            gross += sum(eligible) + nbc + fixed
            earned += sum(base) + bonus
        annual_imports = sum(w * v for w, v in zip(weights, imports))
        annual_exports = sum(w * v for w, v in zip(weights, exports))
        surplus = annual_exports - arithmetic.minimum(annual_exports, annual_imports)
        if self.adjustment_rate is None:
            if not missing_rate_lower_bound and surplus > 0:
                raise ValueError(
                    f"{self.policy.utility.value} optimization cannot be certified: positive "
                    f"annual net exports require an EEC adjustment rate for {self.true_up_month}"
                )
            adjustment = zero
        else:
            adjustment = self.pool(
                surplus * self.adjustment_rate.generation_rate_usd_per_kwh,
                surplus * self.adjustment_rate.delivery_rate_usd_per_kwh,
            )
        annual = annual_accounting(
            opening_base=balance, opening_bonus=bonus_balance,
            prior_paid=tuple(sum(row.paid_eligible[i] for row in rows) for i in range(len(zero))),
            adjustment=adjustment, nsc=surplus * self.nsc_rate.rate_usd_per_kwh,
            offset_prior_payments=self.policy.apply_remaining_eec_to_prior_charges,
            carry_base_credit=self.policy.carry_remaining_eec_forward, arithmetic=arithmetic,
        )
        return NBTBillValues(
            months=tuple(rows), annual=annual, gross_charge_usd=gross,
            earned_credit_usd=earned, net_surplus_kwh=surplus,
            amount_due_usd=sum(row.payment for row in rows) + annual.bill_adjustment,
        )
