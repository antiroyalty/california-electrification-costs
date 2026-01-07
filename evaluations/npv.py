from __future__ import annotations

from typing import Iterable


def annuity_factor(rate: float, n_years: float) -> float:
    """Return annuity factor A such that EAC = NPV * A.

    A = r / (1 - (1 + r)^-n). For non‑positive rate, approximate as 1/n.
    """
    r = float(rate)
    n = float(n_years)
    if n <= 0:
        return 1.0
    if r <= 0:
        return 1.0 / n
    return r / (1.0 - (1.0 + r) ** (-n))


def npv(rate: float, cash_flows: Iterable[float]) -> float:
    """Net Present Value for a sequence of cash flows.

    Cash flows are ordered by period t = 0, 1, 2, ...
    """
    r = float(rate)
    total = 0.0
    for t, cf in enumerate(cash_flows):
        try:
            total += float(cf) / ((1.0 + r) ** t)
        except Exception:
            continue
    return float(total)
