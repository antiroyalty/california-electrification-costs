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

def sweep_csv_path(slug: str, regime: str = "post_itc_2026") -> Path:
    """Cache path for a county sweep. Keyed by regime, since the sweep depends on
    solar's price, which differs between policy regimes."""
    return SWEEP_DIR / f"sweep_8760_{slug}_{regime}.csv"


# --- one claims snapshot per commit -----------------------------------------
# The review doc follows a one-page-per-commit convention: claims-<sha>.html.
# Recipes always target the CURRENT commit's file so an archived snapshot from a
# prior commit is never overwritten.
import re as _re


def git_short_sha() -> str:
    """Short sha of HEAD. Uses rev-parse directly so it never carries a
    `-dirty` suffix (which would corrupt the filename)."""
    import subprocess
    return subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"], cwd=REPO, text=True).strip()


def latest_claims_snapshot(exclude: Path = None):
    """Most recently modified claims-<sha>.html snapshot on disk, or None. The
    Apple-Notes style variant and other non-sha files are ignored."""
    cands = [p for p in REPO.glob("claims-*.html")
             if _re.fullmatch(r"claims-[0-9a-f]{7,40}\.html", p.name) and p != exclude]
    return max(cands, key=lambda p: p.stat().st_mtime) if cands else None


def current_claims_doc(seed: bool = True) -> Path:
    """Path to the combined claims doc for the CURRENT commit
    (claims-<sha>.html). If it does not exist yet and `seed` is True, copy it
    forward from the most recent existing snapshot, so a new commit gets its own
    file to patch instead of overwriting an archived one."""
    import shutil
    target = REPO / f"claims-{git_short_sha()}.html"
    if seed and not target.exists():
        prior = latest_claims_snapshot(exclude=target)
        if prior is None:
            raise FileNotFoundError(
                "no existing claims-<sha>.html to seed a new snapshot from")
        shutil.copy(prior, target)
        print(f"[figure_builder] seeded {target.name} from {prior.name}")
    return target
