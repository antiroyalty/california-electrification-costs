from __future__ import annotations

from dataclasses import dataclass
from math import ceil, fsum, isfinite
from typing import Mapping, Optional

import pandas as pd

from .constants import DEFAULT_DISCOUNT_RATE


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

    Returns an EACComponents dataclass.
    """
    lifetimes = lifetimes or {"solar": 25, "storage": 15}
    inc = (incentive or "").lower()

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
        capex_pv=capex_pv,
        capex_storage=capex_storage,
        capex_electric=capex_electric,
        capex_gas=capex_gas,
        annual_bill_electric=_to_float(annual_bill_electric),
        annual_bill_gas=_to_float(annual_bill_gas),
        vehicle_om=_to_float(vehicle_om),
    )
