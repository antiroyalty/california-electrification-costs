from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .accounting import (
    ComponentAmounts,
    CreditBalances,
    MonthlySettlement,
    PooledAmount,
    settle_month,
)
from .models import EnergyFlows, TariffBundle, Utility, annual_net_surplus_kwh
from .true_up import (
    AverageRetailExportCompensationSchedule,
    NetSurplusCompensationSchedule,
    TrueUpPolicy,
    TrueUpSettlement,
    calculate_true_up_settlement,
)


@dataclass(frozen=True)
class MonthlyBill:
    month: int
    import_kwh: float
    export_kwh: float
    generation_import_charge: float
    delivery_import_charge: float
    generation_export_credit_earned: float
    delivery_export_credit_earned: float
    accounting: MonthlySettlement

    @property
    def amount_due(self) -> float:
        return self.accounting.payment_usd


@dataclass(frozen=True)
class BillLedger:
    utility: Utility
    billing_year: int
    nbt_vintage: int
    months: tuple[MonthlyBill, ...]
    opening: CreditBalances
    true_up_settlement: TrueUpSettlement

    @property
    def closing(self) -> CreditBalances:
        return self.true_up_settlement.accounting.closing

    @property
    def ending_base_credit_bank(self) -> float:
        return self.closing.base.total_usd

    @property
    def ending_acc_plus_credit_bank(self) -> float:
        return self.closing.bonus_usd

    @property
    def monthly_amount_due(self) -> float:
        """Charges paid through monthly bills before the annual true-up."""
        return sum(month.amount_due for month in self.months)

    @property
    def annual_amount_due(self) -> float:
        return self.monthly_amount_due + self.true_up_settlement.net_bill_adjustment

    @property
    def annual_import_kwh(self) -> float:
        return sum(month.import_kwh for month in self.months)

    @property
    def annual_export_kwh(self) -> float:
        return sum(month.export_kwh for month in self.months)

    @property
    def annual_base_export_credit(self) -> float:
        return sum(month.accounting.earned.base.total_usd for month in self.months)

    @property
    def annual_acc_plus_credit(self) -> float:
        return sum(month.accounting.earned.bonus_usd for month in self.months)

    @property
    def annual_base_credit_applied(self) -> float:
        monthly = sum(month.accounting.base_applied.total_usd for month in self.months)
        annual = self.true_up_settlement.accounting
        return (
            monthly
            + annual.base_applied_to_adjustment.total_usd
            + annual.base_applied_to_prior_payments.total_usd
        )

    @property
    def annual_acc_plus_credit_applied(self) -> float:
        return sum(month.accounting.bonus_applied_usd for month in self.months)

    @property
    def annual_credit_earned(self) -> float:
        return self.annual_base_export_credit + self.annual_acc_plus_credit

    @property
    def annual_credit_applied(self) -> float:
        return self.annual_base_credit_applied + self.annual_acc_plus_credit_applied

    @property
    def expired_base_credit(self) -> float:
        """Base EEC forfeited at true-up under the utility's policy."""
        return self.true_up_settlement.total_forfeited_credit

    @property
    def unused_credit(self) -> float:
        """Available credit left unused, including any supplied opening banks."""
        return self.closing.base.total_usd + self.closing.bonus_usd + self.expired_base_credit

    @property
    def annual_credit_available(self) -> float:
        return self.opening.base.total_usd + self.opening.bonus_usd + self.annual_credit_earned

    @property
    def credit_saturation_ratio(self) -> float:
        """Fraction of available credit left unused; zero when none is available."""
        available = self.annual_credit_available
        if available == 0.0:
            return 0.0
        return self.unused_credit / available


def _validate_billing_year(frame: pd.DataFrame, billing_year: int) -> None:
    years = set(frame["timestamp"].dt.year)
    if years != {billing_year}:
        raise ValueError(
            f"Energy-flow timestamps must be calendarized to billing year {billing_year}; "
            f"found years {sorted(years)}"
        )


def calculate_nbt_bill(
    flows: EnergyFlows,
    tariff: TariffBundle,
    *,
    opening: CreditBalances | None = None,
    adjustment_schedule: AverageRetailExportCompensationSchedule | None = None,
    nsc_schedule: NetSurplusCompensationSchedule | None = None,
) -> BillLedger:
    """Calculate a monthly NBT ledger without hourly import/export netting.

    Normalize hourly rates and flows into dollar charges and earned credits.
    The shared accounting core applies credits and settles the modeled year.
    SCE bundled energy uses a combined pool; PG&E and SDG&E use components.
    Omitted opening balances mean the study's zero-opening-bank assumption.
    Pass a previous ledger's ``closing`` to model a specified following year.
    """

    frame = flows.validated_frame()
    _validate_billing_year(frame, tariff.scenario.billing_year)
    timestamps = pd.DatetimeIndex(frame["timestamp"])
    import_rates = tariff.import_schedule.rates_for(timestamps)
    generation_import_rates = tariff.import_schedule.rates_for(timestamps, component="generation")
    delivery_import_rates = tariff.import_schedule.rates_for(timestamps, component="delivery")
    generation_export_rates = tariff.export_schedule.rates_for(timestamps, component="generation")
    delivery_export_rates = tariff.export_schedule.rates_for(timestamps, component="delivery")
    frame["import_rate"] = import_rates
    frame["generation_import_rate"] = generation_import_rates
    frame["delivery_import_rate"] = delivery_import_rates
    frame["generation_export_rate"] = generation_export_rates
    frame["delivery_export_rate"] = delivery_export_rates
    component_gap = (
        frame["import_rate"]
        - frame["generation_import_rate"]
        - frame["delivery_import_rate"]
    ).abs().max()
    if component_gap > 1e-6:
        raise ValueError(
            f"Import generation + delivery rates do not reconcile to total; max gap={component_gap}"
        )
    frame["month"] = frame["timestamp"].dt.month

    policy = TrueUpPolicy.for_utility(tariff.utility)
    if opening is None:
        opening = CreditBalances(policy.energy_amounts(0, 0), 0)
    if not isinstance(opening, CreditBalances):
        raise TypeError("opening must be CreditBalances")
    policy.validate_energy_amounts(opening.base)
    balances = opening
    month_rows: list[MonthlyBill] = []
    for month, group in frame.groupby("month", sort=True):
        imports = float(group["import_kwh"].sum())
        exports = float(group["export_kwh"].sum())
        generation_import_charge = float(
            (group["import_kwh"] * group["generation_import_rate"]).sum()
        )
        delivery_import_charge = float(
            (group["import_kwh"] * group["delivery_import_rate"]).sum()
        )
        generation_non_offsettable = (
            imports * tariff.import_schedule.generation_non_offsettable_rate
        )
        delivery_non_offsettable = (
            imports * tariff.import_schedule.delivery_non_offsettable_rate
        )
        nbc_charge = generation_non_offsettable + delivery_non_offsettable
        if nbc_charge > generation_import_charge + delivery_import_charge + 1e-9:
            raise ValueError(
                f"NBC charge exceeds total import charge in month {month}; "
                "check the configured NBC rate"
            )
        # Subtract rates before aggregation. Equal import and NBC rates then
        # produce exactly zero eligible charge, without subtracting rounded totals.
        eligible_generation_rates = (
            group["generation_import_rate"]
            - tariff.import_schedule.generation_non_offsettable_rate
        )
        eligible_delivery_rates = (
            group["delivery_import_rate"]
            - tariff.import_schedule.delivery_non_offsettable_rate
        )
        eligible_generation = float((group["import_kwh"] * eligible_generation_rates).sum())
        eligible_delivery = float((group["import_kwh"] * eligible_delivery_rates).sum())
        if eligible_generation < 0 or eligible_delivery < 0:
            raise ValueError(
                f"Non-offsettable charges exceed an import component in month {month}"
            )
        generation_earned = float(
            (group["export_kwh"] * group["generation_export_rate"]).sum()
        )
        delivery_earned = float(
            (group["export_kwh"] * group["delivery_export_rate"]).sum()
        )
        days = pd.DatetimeIndex(group["timestamp"]).normalize().unique()
        fixed_charge = sum(
            tariff.import_schedule.daily_fixed_charge(pd.Timestamp(day)) for day in days
        )
        accounting = settle_month(
            eligible_energy=policy.energy_amounts(eligible_generation, eligible_delivery),
            non_bypassable_charge_usd=nbc_charge,
            fixed_charge_usd=fixed_charge,
            opening=balances,
            earned=CreditBalances(
                policy.energy_amounts(generation_earned, delivery_earned),
                exports * tariff.acc_plus_rate,
            ),
        )
        balances = accounting.closing
        month_rows.append(
            MonthlyBill(
                month=int(month),
                import_kwh=imports,
                export_kwh=exports,
                generation_import_charge=generation_import_charge,
                delivery_import_charge=delivery_import_charge,
                generation_export_credit_earned=generation_earned,
                delivery_export_credit_earned=delivery_earned,
                accounting=accounting,
            )
        )

    annual_import_kwh = float(frame["import_kwh"].sum())
    annual_export_kwh = float(frame["export_kwh"].sum())
    net_surplus_kwh = annual_net_surplus_kwh(annual_import_kwh, annual_export_kwh)
    adjustment_rate = None
    nsc_rate = None
    if net_surplus_kwh > 0:
        resolved_adjustment_schedule = (
            adjustment_schedule
            or AverageRetailExportCompensationSchedule.from_csv()
        )
        resolved_nsc_schedule = (
            nsc_schedule or NetSurplusCompensationSchedule.from_csv()
        )
        adjustment_rate = resolved_adjustment_schedule.resolve(
            tariff.utility, tariff.scenario.true_up_month
        )
        nsc_rate = resolved_nsc_schedule.resolve(
            tariff.utility, tariff.scenario.true_up_month
        )

    paid_energy = [row.accounting.paid_eligible_energy for row in month_rows]
    if isinstance(balances.base, PooledAmount):
        prior_paid = PooledAmount(sum(amount.total_usd for amount in paid_energy))
    else:
        prior_paid = ComponentAmounts(
            sum(amount.generation_usd for amount in paid_energy),
            sum(amount.delivery_usd for amount in paid_energy),
        )
    true_up_settlement = calculate_true_up_settlement(
        policy=policy,
        annual_import_kwh=annual_import_kwh,
        annual_export_kwh=annual_export_kwh,
        opening=balances,
        prior_paid_eligible_energy=prior_paid,
        adjustment_rate=adjustment_rate,
        nsc_rate=nsc_rate,
        true_up_month=tariff.scenario.true_up_month,
    )

    return BillLedger(
        utility=tariff.utility,
        billing_year=tariff.scenario.billing_year,
        nbt_vintage=tariff.scenario.nbt_vintage,
        months=tuple(month_rows),
        opening=opening,
        true_up_settlement=true_up_settlement,
    )
