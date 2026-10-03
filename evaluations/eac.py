from __future__ import annotations

from dataclasses import dataclass
from math import ceil, fsum, isfinite
from numbers import Real
from typing import Mapping, Optional

import pandas as pd

from .constants import DEFAULT_DISCOUNT_RATE
from .federal_credits import FederalCreditReceipts, HouseholdFederalCredits


def crf(rate: float, years: float) -> float:
    """Capital Recovery Factor.

    For non‑positive rate or years, fall back to straight‑line (1 / years).
    """
    r = float(rate)
    n = float(years)
    if n <= 0:
        return 1.0
    if r <= 0:
        return 1.0 / n
    return (r * (1 + r) ** n) / (((1 + r) ** n) - 1)


def annualized_one_time_credit(
    *,
    credit_usd: float,
    receipt_year: float,
    discount_rate: float,
    horizon_years: float,
) -> float:
    """Return a positive annual cost reduction for one declared credit receipt.

    Dollars must use the study's constant-dollar basis with a real discount rate.
    receipt_year is elapsed time from purchase: 0 means immediate receipt and
    1 means receipt one year later. Fractional years are allowed. The receipt
    must occur within the study, including its endpoint.

    Subtract the result from annual costs calculated before this credit. Use the
    study horizon, not an appliance's service life. Replacement purchases and
    remaining value retain their gross cost basis; this credit is received once.
    The caller must declare the amount actually realized and its receipt time.
    This function does not determine eligibility, tax liability, or carryforward.
    """
    values = {
        "credit_usd": credit_usd,
        "receipt_year": receipt_year,
        "discount_rate": discount_rate,
        "horizon_years": horizon_years,
    }
    for name, value in values.items():
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError(f"{name} must be a finite real number")
        try:
            value = float(value)
        except OverflowError as exc:
            raise ValueError(f"{name} must be a finite real number") from exc
        if not isfinite(value):
            raise ValueError(f"{name} must be a finite real number")
        values[name] = value
    credit = values["credit_usd"]
    t = values["receipt_year"]
    r = values["discount_rate"]
    N = values["horizon_years"]
    if credit < 0:
        raise ValueError("credit_usd must be nonnegative")
    if r < 0:
        raise ValueError("discount_rate must be nonnegative")
    if N <= 0:
        raise ValueError("horizon_years must be positive")
    if not 0 <= t <= N:
        raise ValueError("receipt_year must be between zero and horizon_years")

    present_credit = credit * (1 + r) ** (-t)
    return present_credit * crf(r, N)


@dataclass
class EACComponents:
    """Equivalent Annual Cost components for a single county + scenario.

    All values are annualized ($/year) except `annual_bill_*`, which are
    already annual flows from the tariff calculation.
    """

    capex_pv: float = 0.0
    capex_storage: float = 0.0
    capex_electric: float = 0.0
    capex_gas: float = 0.0
    annual_bill_electric: float = 0.0
    annual_bill_gas: float = 0.0
    vehicle_om: float = 0.0

    def total(self) -> float:
        return (
            self.capex_pv
            + self.capex_storage
            + self.capex_electric
            + self.capex_gas
            + self.annual_bill_electric
            + self.annual_bill_gas
            + self.vehicle_om
        )


def _to_float(val, default: float = 0.0) -> float:
    try:
        return float(val)
    except Exception:
        return float(default)


def alpha_batt_npv(discount_rate: float, batt_life_yrs: float, horizon_yrs: float) -> float:
    """Annual battery capital cost per dollar of modeled purchase cost.

    Buy initially and at each service-life boundary strictly before study end.
    Each purchase has the same real cost and incentive treatment. At study end,
    credit the last battery's unused fraction of service life at that cost basis.
    Discount all purchases and the credit, then annualize their net present cost.

    A 25-year study with 15-year batteries buys at years 0 and 15 and credits
    one-third of purchase cost at year 25. With zero interest the coefficient
    is 1 / batt_life_yrs. Negative discount rates are outside the modeled domain.

    Remaining-life method: NIST Handbook 135 (2022), section 4.5.3.
    https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=934909
    """
    r = float(discount_rate)
    n = float(batt_life_yrs)
    N = float(horizon_yrs)
    if not isfinite(r) or r < 0:
        raise ValueError("discount_rate must be finite and nonnegative")
    for name, value in (("batt_life_yrs", n), ("horizon_yrs", N)):
        if not isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")

    purchase_count = ceil(N / n)
    discounted_purchases = fsum(
        (1 + r) ** (-purchase * n) for purchase in range(purchase_count)
    )
    remaining_life_fraction = (purchase_count * n - N) / n
    discounted_remaining_value = remaining_life_fraction * (1 + r) ** (-N)
    return (discounted_purchases - discounted_remaining_value) * crf(r, N)


def _gross_federal_inputs(ledger_df, pv_summary_row):
    """Validate gross costs and remove mixed-incentive prices from copied inputs."""
    ledger = None
    if ledger_df is not None:
        if not isinstance(ledger_df, pd.DataFrame):
            raise ValueError("Federal-only ledger must be a DataFrame or explicit None")
        required = {"appliance_category", "appliance_type", "base_cost", "lifetime_years"}
        missing = required - set(ledger_df.columns)
        if missing:
            raise ValueError(f"Federal-only ledger missing columns: {sorted(missing)}")
        ledger = ledger_df.copy()
        for key in ("county_slug", "incentive_scenario"):
            if key in ledger and (ledger[key].isna().any() or ledger[key].nunique() != 1):
                raise ValueError(f"Federal-only ledger requires one selected {key}")
        if not ledger["appliance_category"].isin(["electric", "gas"]).all():
            raise ValueError("Federal-only appliance_category must be electric or gas")
        if not ledger["appliance_type"].map(
            lambda value: isinstance(value, str) and bool(value.strip())
        ).all():
            raise ValueError("Federal-only appliance_type must be non-empty text")
        if ledger.duplicated(["appliance_category", "appliance_type"]).any():
            raise ValueError("Federal-only ledger has duplicate appliance rows")
        for column in ("base_cost", "lifetime_years"):
            try:
                ledger[column] = pd.to_numeric(ledger[column], errors="raise")
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Federal-only {column} must be numeric") from exc
            if not ledger[column].map(lambda value: isfinite(value)).all():
                raise ValueError(f"Federal-only {column} must be finite")
        if (ledger["base_cost"] < 0).any():
            raise ValueError("Federal-only base_cost must be nonnegative")
        if (ledger["lifetime_years"] <= 0).any():
            raise ValueError("Federal-only lifetime_years must be positive")
        ledger["net_cost"] = ledger["base_cost"]

    pv_summary = None
    if pv_summary_row is not None:
        pv_summary = {}
        for column in ("pv_capex", "storage_capex"):
            if column not in pv_summary_row:
                raise ValueError(f"Federal-only PV summary missing {column}")
            value = pv_summary_row[column]
            if isinstance(value, bool) or not isinstance(value, Real):
                raise ValueError(f"Federal-only {column} must be numeric")
            if not isfinite(value) or value < 0:
                raise ValueError(f"Federal-only {column} must be finite and nonnegative")
            pv_summary[column] = float(value)
        # These zeros deliberately exclude all legacy PV/storage incentives.
        pv_summary.update(pv_incentives_full=0.0, storage_incentives_full=0.0)
    return ledger, pv_summary


def compute_eac_from_inputs(
    ledger_df: Optional[pd.DataFrame],
    pv_summary_row: Optional[pd.Series | Mapping[str, float]],
    *,
    incentive: str = "full_incentives",
    discount_rate: float = DEFAULT_DISCOUNT_RATE,
    lifetimes: Optional[Mapping[str, float]] = None,
    annual_bill_electric: float = 0.0,
    annual_bill_gas: float = 0.0,
    vehicle_om: float = 0.0,
    federal_credit_receipts: FederalCreditReceipts | None = None,
) -> EACComponents:
    """Compute EAC components from in‑memory inputs.

    Parameters
    - ledger_df: Capital ledger for a single county+scenario (already filtered
      for county/incentive). Expected columns (best‑effort):
        - appliance_category: 'electric' | 'gas'
        - appliance_type: identifies PV/storage rows (excluded from electric capex)
        - net_cost: for electrification assets
        - base_cost: for gas assets
        - lifetime_years: annualization horizon per row (default 15)
      If missing or None, non‑PV/storage capex components are zero.

    - pv_summary_row: Row with PV/storage capex and incentives for this
      county+scenario from capital_costs_summary_with_pv_*.csv. Expected keys:
        pv_capex, storage_capex, pv_incentives_full, storage_incentives_full.
      If missing or None, PV/storage capex components are zero.

    - incentive: 'full_incentives' | 'half_incentives' | 'no_incentives'
    - discount_rate: real discount rate used for annualization
    - lifetimes: mapping with keys 'solar' and 'storage' (defaults used if None)
      The study period equals solar life. Storage includes replacements and
      proportional remaining value through alpha_batt_npv, as in optimization.
    - annual_bill_electric, annual_bill_gas: already‑computed annual bills
    - vehicle_om: optional annual vehicle O&M adder (default 0)
    - federal_credit_receipts: explicit federal-only comparison. Use gross
      equipment costs and subtract these initial credits once over the study
      horizon. This replaces all ledger/PV incentives, including rebates. The
      returned capital components are net of annualized credits. None preserves
      existing mixed-incentive reporting. It does not mean zero federal credits;
      supply explicit zero amounts for the federal-only no-credit comparison.

    Returns an EACComponents dataclass.
    """
    lifetimes = lifetimes or {"solar": 25, "storage": 15}
    inc = (incentive or "").lower()

    credit_pv = credit_storage = credit_heat = credit_vehicle = 0.0
    if federal_credit_receipts is not None:
        receipts = federal_credit_receipts
        if not isinstance(receipts, FederalCreditReceipts) or not isinstance(
            receipts.amounts, HouseholdFederalCredits
        ):
            raise ValueError("federal_credit_receipts must contain HouseholdFederalCredits")
        ledger_df, pv_summary_row = _gross_federal_inputs(ledger_df, pv_summary_row)
        inc = "no_incentives"
        for name, value in (("annual_bill_electric", annual_bill_electric),
                            ("annual_bill_gas", annual_bill_gas), ("vehicle_om", vehicle_om)):
            if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value):
                raise ValueError(f"Federal-only {name} must be finite and numeric")
        heat_basis = vehicle_basis = 0.0
        if ledger_df is not None:
            electric = ledger_df[ledger_df["appliance_category"] == "electric"]
            heat_basis = electric.loc[
                electric["appliance_type"].isin(["heating", "hot_water"]), "base_cost"
            ].sum()
            vehicle_basis = electric.loc[
                electric["appliance_type"] == "vehicle_charging", "base_cost"
            ].sum()
        pv_basis = 0.0 if pv_summary_row is None else pv_summary_row["pv_capex"]
        storage_basis = 0.0 if pv_summary_row is None else pv_summary_row["storage_capex"]
        amounts = receipts.amounts
        reductions = []
        for name, amount, basis, time in (
            ("pv_25d_usd", amounts.pv_25d_usd, pv_basis, receipts.home_receipt_year),
            ("storage_25d_usd", amounts.storage_25d_usd, storage_basis, receipts.home_receipt_year),
            ("heat_pumps_25c_usd", amounts.heat_pumps_25c_usd, heat_basis, receipts.home_receipt_year),
            ("vehicle_30d_usd", amounts.vehicle_30d_usd, vehicle_basis, receipts.vehicle_receipt_year),
        ):
            reduction = annualized_one_time_credit(
                credit_usd=amount, receipt_year=time, discount_rate=discount_rate,
                horizon_years=lifetimes.get("solar", 25),
            )
            if amount > basis:
                raise ValueError(f"Federal-only {name} exceeds the corresponding gross purchase cost")
            reductions.append(reduction)
        credit_pv, credit_storage, credit_heat, credit_vehicle = reductions

    capex_electric = 0.0
    capex_gas = 0.0

    if ledger_df is not None and not ledger_df.empty:
        df = ledger_df.copy()
        # Best‑effort guards for missing columns
        if "appliance_category" not in df.columns:
            df["appliance_category"] = ""
        if "appliance_type" not in df.columns:
            df["appliance_type"] = ""
        if "lifetime_years" not in df.columns:
            df["lifetime_years"] = 15

        for _, r in df.iterrows():
            try:
                lt = _to_float(r.get("lifetime_years", 15), 15)
                factor = crf(discount_rate, lt)
                if r.get("appliance_category") == "electric" and r.get("appliance_type") not in ("solar", "storage"):
                    capex_electric += _to_float(r.get("net_cost", 0.0)) * factor
                if r.get("appliance_category") == "gas":
                    capex_gas += _to_float(r.get("base_cost", 0.0)) * factor
            except Exception:
                if federal_credit_receipts is not None:
                    raise
                # Skip any malformed rows
                continue

    capex_pv = 0.0
    capex_storage = 0.0
    if pv_summary_row is not None:
        s = pv_summary_row
        # Support dict‑like and Series access
        pv_capex = _to_float(s.get("pv_capex", 0.0)) if hasattr(s, "get") else _to_float(s["pv_capex"])  # type: ignore[index]
        st_capex = _to_float(s.get("storage_capex", 0.0)) if hasattr(s, "get") else _to_float(s["storage_capex"])  # type: ignore[index]
        pv_inc_full = _to_float(s.get("pv_incentives_full", 0.0)) if hasattr(s, "get") else _to_float(s.get("pv_incentives_full", 0.0))  # type: ignore[attr-defined]
        st_inc_full = _to_float(s.get("storage_incentives_full", 0.0)) if hasattr(s, "get") else _to_float(s.get("storage_incentives_full", 0.0))  # type: ignore[attr-defined]

        if inc == "full_incentives":
            pv_net = pv_capex - pv_inc_full
            st_net = st_capex - st_inc_full
        elif inc == "half_incentives":
            pv_net = pv_capex - (pv_inc_full * 0.5)
            st_net = st_capex - (st_inc_full * 0.5)
        else:
            pv_net = pv_capex
            st_net = st_capex

        solar_life = float(lifetimes.get("solar", 25))
        storage_life = float(lifetimes.get("storage", 15))
        capex_pv = pv_net * crf(discount_rate, solar_life)
        capex_storage = st_net * alpha_batt_npv(discount_rate, storage_life, solar_life)

    return EACComponents(
        capex_pv=capex_pv - credit_pv,
        capex_storage=capex_storage - credit_storage,
        capex_electric=capex_electric - credit_heat - credit_vehicle,
        capex_gas=capex_gas,
        annual_bill_electric=_to_float(annual_bill_electric),
        annual_bill_gas=_to_float(annual_bill_gas),
        vehicle_om=_to_float(vehicle_om),
    )
