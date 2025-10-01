"""
Custom dispatch logging utilities.

Provides concise summaries and sample windows for verifying hourly profiles
produced by the custom battery dispatch step.
"""

from __future__ import annotations

from typing import Dict, List
import statistics


def _round_list(v: List[float], ndigits: int = 3) -> List[float]:
    return [round(x, ndigits) for x in v]


def summarize_series(series: List[float]) -> Dict[str, float]:
    if not series:
        return {"min": 0.0, "max": 0.0, "mean": 0.0, "total": 0.0}
    return {
        "min": round(min(series), 4),
        "max": round(max(series), 4),
        "mean": round(statistics.mean(series), 4),
        "total": round(sum(series), 3),
    }


def log_profiles(series_map: Dict[str, List[float]], title: str | None = None) -> None:
    """Print concise profile summaries and a short sample window for each series.

    series_map keys are labels; values are 8760 lists.
    """
    if title:
        print("\n" + "=" * 80)
        print(title)
        print("=" * 80)

    window_start, window_end = 5, 20  # show 15-hour window for quick inspection
    for name, arr in series_map.items():
        stats = summarize_series(arr)
        sample = _round_list(arr[window_start:window_end]) if len(arr) >= window_end else _round_list(arr)
        print(f"\n{name} :: total={stats['total']} min={stats['min']} max={stats['max']} mean={stats['mean']}")
        print(f"  sample[{window_start}:{window_end}]: {sample}")

