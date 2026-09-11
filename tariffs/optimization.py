"""Normalize NBT tariff rates and aggregate annual dollars for shared settlement."""

from dataclasses import dataclass
import math
from typing import Sequence

import pandas as pd

from .accounting import Amount, AnnualCreditSettlement, settle_annual_credits
from .models import TariffBundle, Utility, require_annual_export_cap


@dataclass(frozen=True)
class NBTOptimizationTerms:
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
            self.nbc_rate_usd_per_kwh,
            *(v for rows in (self.eligible_rates_usd_per_kwh, self.base_export_rates_usd_per_kwh)
              for row in rows for v in row),
            *(v for _, v in self.fixed_charges_usd),
        ]
        if any(not math.isfinite(v) or v < 0 for v in prices):
            raise ValueError("NBT prices must be finite and non-negative")

    def pool(self, generation, delivery):
        # SCE Schedule NBT 3.a.i/ii and 4.b combine bundled energy charges.
        if self.utility is Utility.SCE:
            return (generation + delivery,)
        return (generation, delivery)

    @property
    def pool_names(self):
        return ("energy",) if self.utility is Utility.SCE else ("generation", "delivery")

    @property
    def import_rates(self):
        return tuple(
            sum(row) + self.nbc_rate_usd_per_kwh for row in self.eligible_rates_usd_per_kwh
        )

    @property
    def export_rates(self):
        return tuple(
            sum(row) for row in self.base_export_rates_usd_per_kwh
        )

    @classmethod
    def from_tariff(
        cls, tariff: TariffBundle, timestamps,
    ):
        timestamps = pd.DatetimeIndex(timestamps)
        if (timestamps.empty or timestamps.hasnans or timestamps.has_duplicates
                or not timestamps.is_monotonic_increasing):
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
            if any(not math.isfinite(v) or v < 0 for v in (g, d, eg, ed)):
                raise ValueError("NBT component rates must be finite and non-negative")
            eligible.append(pools(g, d))
            exports.append(pools(eg, ed))
        fixed = tuple(
            (int(m), sum(schedule.daily_fixed_charge(day) for day in
                         timestamps[timestamps.month == m].normalize().unique()))
            for m in sorted(set(timestamps.month))
        )
        return cls(
            billing_year=tariff.scenario.billing_year,
            billing_months=tuple(int(m) for m in timestamps.month),
            eligible_rates_usd_per_kwh=tuple(eligible),
            base_export_rates_usd_per_kwh=tuple(exports),
            nbc_rate_usd_per_kwh=(schedule.generation_non_offsettable_rate
                                 + schedule.delivery_non_offsettable_rate),
            fixed_charges_usd=fixed, utility=tariff.utility,
        )

    def bill(
        self, imports: Sequence[Amount], exports: Sequence[Amount], weights: Sequence[float],
        *, positive_part=None, sum_amounts=math.fsum,
    ) -> AnnualCreditSettlement[Amount]:
        """Aggregate interval dollars, then settle the annual eligible pools.

        Symbolic callers provide a linear sum and positive-part expression.
        They must enforce the annual energy cap in their physical model. Numeric
        reporting validates the cap here, including representative-hour weights.
        """
        count = len(self.billing_months)
        if not (len(imports) == len(exports) == len(weights) == count):
            raise ValueError("NBT meter flows and weights must match the tariff intervals")
        if any(not math.isfinite(w) or w <= 0 for w in weights):
            raise ValueError("NBT interval weights must be finite and positive")
        if positive_part is None:
            if any(not math.isfinite(v) or v < 0 for v in (*imports, *exports)):
                raise ValueError("NBT meter flows must be finite and non-negative")
            require_annual_export_cap(
                math.fsum(w * v for w, v in zip(weights, imports)),
                math.fsum(w * v for w, v in zip(weights, exports)),
            )
        eligible = tuple(sum_amounts(
            weights[h] * imports[h] * self.eligible_rates_usd_per_kwh[h][i]
            for h in range(count)
        ) for i in range(len(self.pool_names)))
        credits = tuple(sum_amounts(
            weights[h] * exports[h] * self.base_export_rates_usd_per_kwh[h][i]
            for h in range(count)
        ) for i in range(len(self.pool_names)))
        nbc = sum_amounts(w * v for w, v in zip(weights, imports)) * self.nbc_rate_usd_per_kwh
        return settle_annual_credits(
            eligible, credits, nbc, math.fsum(v for _, v in self.fixed_charges_usd),
            positive_part=positive_part,
        )
