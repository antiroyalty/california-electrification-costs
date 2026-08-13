from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .models import EnergyFlows, TariffBundle, Utility
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
    import_energy_charge: float
    non_bypassable_charge: float
    fixed_charge: float
    base_export_credit_earned: float
    acc_plus_credit_earned: float
    base_credit_applied: float
    acc_plus_credit_applied: float
    amount_due: float
    ending_base_credit_bank: float
    ending_acc_plus_credit_bank: float
    generation_import_charge: float
    delivery_import_charge: float
    generation_export_credit_earned: float
    delivery_export_credit_earned: float
    ending_generation_credit_bank: float
    ending_delivery_credit_bank: float


@dataclass(frozen=True)
class BillLedger:
    utility: Utility
    billing_year: int
    nbt_vintage: int
    months: tuple[MonthlyBill, ...]
    ending_base_credit_bank: float
    ending_acc_plus_credit_bank: float
    true_up_settlement: TrueUpSettlement

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
        return sum(month.base_export_credit_earned for month in self.months)

    @property
    def annual_acc_plus_credit(self) -> float:
        return sum(month.acc_plus_credit_earned for month in self.months)

    @property
    def annual_base_credit_applied(self) -> float:
        monthly = sum(month.base_credit_applied for month in self.months)
        true_up = self.true_up_settlement
        return monthly + sum(
            (
                true_up.generation_eec_applied_to_adjustment,
                true_up.delivery_eec_applied_to_adjustment,
                true_up.generation_eec_applied_to_prior_charges,
                true_up.delivery_eec_applied_to_prior_charges,
            )
        )

    @property
    def annual_acc_plus_credit_applied(self) -> float:
        return sum(month.acc_plus_credit_applied for month in self.months)

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
        """Export credit earned over the year that never offset a charge.

        This is the realized-bill counterpart to Step 9b's marginal export
        signal. Step 9b values every exported kWh at its hourly credit rate,
        but the monthly ledger can only apply credit against actual charges;
        the difference shows up here. A large value means the optimizer
        over-valued exports relative to the bill the household actually pays.
        """
        return self.annual_credit_earned - self.annual_credit_applied

    @property
    def credit_saturation_ratio(self) -> float:
        """Fraction of earned export credit that went unused (0.0 when none earned)."""
        earned = self.annual_credit_earned
        if earned <= 0.0:
            return 0.0
        return self.unused_credit / earned


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
    adjustment_schedule: AverageRetailExportCompensationSchedule | None = None,
    nsc_schedule: NetSurplusCompensationSchedule | None = None,
) -> BillLedger:
    """Calculate a monthly NBT ledger without hourly import/export netting.

    Base EEC credits offset volumetric import charges excluding the configured
    NBC portion. ACC Plus credits then offset any remaining energy, NBC, and
    fixed charges. The annual true-up then reconciles remaining component EEC,
    reverses compensation for annual net-surplus kWh at the utility-wide EEC
    adjustment rate, and credits the same kWh at the selected NSC rate.

    Generation EEC offsets only eligible generation imports and delivery EEC
    offsets only eligible delivery imports. Non-offsettable volumetric charges
    are also assigned to the corresponding import component.
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

    generation_bank = 0.0
    delivery_bank = 0.0
    acc_plus_bank = 0.0
    annual_paid_eligible_generation_charge = 0.0
    annual_paid_eligible_delivery_charge = 0.0
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
        eligible_generation = generation_import_charge - generation_non_offsettable
        eligible_delivery = delivery_import_charge - delivery_non_offsettable
        if eligible_generation < -1e-9 or eligible_delivery < -1e-9:
            raise ValueError(
                f"Non-offsettable charges exceed an import component in month {month}"
            )
        generation_earned = float(
            (group["export_kwh"] * group["generation_export_rate"]).sum()
        )
        delivery_earned = float(
            (group["export_kwh"] * group["delivery_export_rate"]).sum()
        )
        base_earned = generation_earned + delivery_earned
        acc_plus_earned = exports * tariff.acc_plus_rate
        generation_bank += generation_earned
        delivery_bank += delivery_earned
        acc_plus_bank += acc_plus_earned

        generation_applied = min(generation_bank, eligible_generation)
        delivery_applied = min(delivery_bank, eligible_delivery)
        generation_bank -= generation_applied
        delivery_bank -= delivery_applied
        base_applied = generation_applied + delivery_applied
        remaining_generation = eligible_generation - generation_applied
        remaining_delivery = eligible_delivery - delivery_applied
        eligible_import_charge = eligible_generation + eligible_delivery
        remaining_energy = remaining_generation + remaining_delivery

        days = pd.DatetimeIndex(group["timestamp"]).normalize().unique()
        fixed_charge = sum(
            tariff.import_schedule.daily_fixed_charge(pd.Timestamp(day)) for day in days
        )
        before_acc_plus = remaining_energy + nbc_charge + fixed_charge
        acc_plus_applied = min(acc_plus_bank, before_acc_plus)
        acc_plus_bank -= acc_plus_applied
        amount_due = before_acc_plus - acc_plus_applied

        # ACC Plus is component-neutral. Allocate the portion that offsets
        # eligible energy proportionally across the remaining generation and
        # delivery charges. Only the residual cash-paid energy charge is
        # eligible for a backward-looking EEC application at annual true-up;
        # passing the pre-ACC-Plus amount would credit the same charge twice.
        acc_plus_applied_to_energy = min(acc_plus_applied, remaining_energy)
        if remaining_energy > 0.0:
            generation_share = remaining_generation / remaining_energy
            acc_plus_applied_to_generation = (
                acc_plus_applied_to_energy * generation_share
            )
        else:
            acc_plus_applied_to_generation = 0.0
        acc_plus_applied_to_delivery = (
            acc_plus_applied_to_energy - acc_plus_applied_to_generation
        )
        annual_paid_eligible_generation_charge += max(
            remaining_generation - acc_plus_applied_to_generation,
            0.0,
        )
        annual_paid_eligible_delivery_charge += max(
            remaining_delivery - acc_plus_applied_to_delivery,
            0.0,
        )
        month_rows.append(
            MonthlyBill(
                month=int(month),
                import_kwh=imports,
                export_kwh=exports,
                import_energy_charge=eligible_import_charge,
                non_bypassable_charge=nbc_charge,
                fixed_charge=fixed_charge,
                base_export_credit_earned=base_earned,
                acc_plus_credit_earned=acc_plus_earned,
                base_credit_applied=base_applied,
                acc_plus_credit_applied=acc_plus_applied,
                amount_due=amount_due,
                ending_base_credit_bank=generation_bank + delivery_bank,
                ending_acc_plus_credit_bank=acc_plus_bank,
                generation_import_charge=generation_import_charge,
                delivery_import_charge=delivery_import_charge,
                generation_export_credit_earned=generation_earned,
                delivery_export_credit_earned=delivery_earned,
                ending_generation_credit_bank=generation_bank,
                ending_delivery_credit_bank=delivery_bank,
            )
        )

    annual_import_kwh = float(frame["import_kwh"].sum())
    annual_export_kwh = float(frame["export_kwh"].sum())
    net_surplus_kwh = max(annual_export_kwh - annual_import_kwh, 0.0)
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

    true_up_settlement = calculate_true_up_settlement(
        policy=TrueUpPolicy.for_utility(tariff.utility),
        annual_import_kwh=annual_import_kwh,
        annual_export_kwh=annual_export_kwh,
        ending_generation_credit_bank=generation_bank,
        ending_delivery_credit_bank=delivery_bank,
        ending_acc_plus_credit_bank=acc_plus_bank,
        remaining_offsettable_generation_charges=(
            annual_paid_eligible_generation_charge
        ),
        remaining_offsettable_delivery_charges=(
            annual_paid_eligible_delivery_charge
        ),
        adjustment_rate=adjustment_rate,
        nsc_rate=nsc_rate,
        true_up_month=tariff.scenario.true_up_month,
    )

    return BillLedger(
        utility=tariff.utility,
        billing_year=tariff.scenario.billing_year,
        nbt_vintage=tariff.scenario.nbt_vintage,
        months=tuple(month_rows),
        ending_base_credit_bank=(
            true_up_settlement.ending_generation_credit_bank
            + true_up_settlement.ending_delivery_credit_bank
        ),
        ending_acc_plus_credit_bank=(
            true_up_settlement.ending_acc_plus_credit_bank
        ),
        true_up_settlement=true_up_settlement,
    )
