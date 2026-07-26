"""figure_builder — the repository's figure-building package.

A small system for reliably regenerating publication figures from the model,
built from testable primitives:

    dispatch   -> per-county 8760-hour load / PV / price inputs
    pricing    -> live capital costs, sourced from the appliance classes
    datasets   -> collectors: model runs -> tidy DataFrames
    charts     -> pure plot functions: DataFrame -> matplotlib Figure
    docio      -> pure string primitives: embed PNGs, patch/splice HTML docs
    recipes    -> compose the above into specific document figures
    __main__   -> CLI driver, emits a figure manifest + run metadata

Finance/LCOE/tariff primitives are reused from the repo's `evaluations` package
(e.g. `evaluations.eac.crf`), not redefined here.
"""
from __future__ import annotations

import sys
from pathlib import Path

# This package lives at <repo>/figure_builder/. Put the repo on the path so the
# collectors can import appliances / helpers / pipeline / evaluations when the
# package is imported from anywhere.
REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# Regenerable intermediates and outputs live inside the package, not in a
# session scratchpad that evaporates between runs.
SWEEP_DIR = REPO / "figure_builder" / "sweeps"
FIG_DIR = REPO / "figure_builder" / "figures"

# The combined review doc the claim recipes patch. Per-claim files are derived
# from it by recipes.split_claims.
COMBINED_DOC = REPO / "claims-c459506.html"


def sweep_csv_path(slug: str) -> Path:
    return SWEEP_DIR / f"sweep_8760_{slug}.csv"
