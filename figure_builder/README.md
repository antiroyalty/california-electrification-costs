# figure_builder

The repository's package for reliably regenerating publication figures from the
model. It replaces a set of one-off scratchpad scripts that were lost whenever a
session's temp directory was cleaned up, and that hardcoded prices which drifted
out of sync with the model.

Built from small, testable primitives. Finance / LCOE / tariff math is reused
from the repo's `evaluations` package (e.g. `evaluations.eac.crf`), not
redefined here.

## Layout

| Module | Responsibility |
|---|---|
| `dispatch.py` | Turn a county slug into 8760-hour load / PV / import / export arrays. |
| `pricing.py` | `live_prices(regime)` — net capital costs, read from the appliance classes so captions can't drift from the model. |
| `datasets.py` | Strict collectors (`collect_*`) that run the model or validate complete, source-locked result tables and return tidy DataFrames. |
| `charts.py` | Pure plot functions (`plot_*`): DataFrame → matplotlib Figure. No IO. |
| `docio.py` | Pure string primitives: embed PNGs, patch/splice HTML documents idempotently. |
| `recipes.py` | Compose the above into specific document figures (Claim 1 mechanism/county figures, statewide Claims 2/3, bridge, split). |
| `__main__.py` | CLI driver; `all` emits `figures/run_metadata.json`. |
| `tests/` | Unit tests for collectors, charts, document IO, pricing, and metadata. |

## Usage

The combined doc follows a **one-page-per-commit** convention: recipes target
`claims-<current-sha>.html` (resolved from `git rev-parse --short HEAD`), never a
hardcoded filename, so a prior commit's archived snapshot is never overwritten.
`snapshot` creates the current commit's file (seeded from the most recent
snapshot) if it does not exist yet; `all`/`mechanism`/`counties` seed it
automatically.

```bash
python3 -m figure_builder snapshot                  # ensure claims-<sha>.html exists

# Normalize three completed scenario runs. Use the exact Git SHA and the
# YYYYMMDD_HH suffixes written by each run's electricity/gas result files.
python3 -m figure_builder claims-source \
  --model-run-sha <model-sha> \
  --scenario-run baseline_ice_car=<timestamp> \
  --scenario-run full_electric_ev=<timestamp> \
  --scenario-run full_electric_ev_coopt=<timestamp>

# Regenerate everything from that exact normalized statewide source.
python3 -m figure_builder all \
  --claims-source analysis_results/claims_eac_by_county_nem3_g<model-sha>.csv

# Or step by step:
python3 -m figure_builder sweeps                    # weighted 12x24 sensitivity sweeps
python3 -m figure_builder sweeps --counties alameda --force
python3 -m figure_builder sweeps --counties alameda --fine  # deliberate 8760 run
python3 -m figure_builder market                    # exact 8760 current-law NBT checks
python3 -m figure_builder policy-matrix             # 2x2 NBT/NEM 2 x ITC comparison
python3 -m figure_builder mechanism                 # Claim-1 Figures A/B/C + objective box
python3 -m figure_builder counties                  # Claim-1 four-county grid
python3 -m figure_builder statewide                 # Claims 2/3 from complete paired EAC results
python3 -m figure_builder bridge                    # assumption-bridge waterfall PNG
python3 -m figure_builder split                     # combined doc -> claim1/2/3.html
```

Sweeps are cached in `figure_builder/sweeps/` as
`sweep_288_<county>_<export-regime>_<capital-regime>.csv` by default, or
`sweep_8760_...` with `--fine`. The two explicit axes prevent NBT and NEM 2
results from sharing a cache. Pass `--force` to recompute. Weighted 12x24 is
the declared sensitivity-grid resolution. The four-cell NBT/NEM 2 policy
comparison uses this same resolution in every cell. The market command retains
the separate exact current-law NBT checks used by Claim 1. Corrected full-year
Southern California MILPs do not complete within a bounded publication
workflow, so the builder does not misrepresent the policy matrix as exact
8,760-hour optima. Use full chronology for targeted checks, not large low-cost
grids. The
cache records the explicit battery-capacity bound and solver diagnostics; a
cache generated under a different sizing domain or the former unbounded model
is rejected automatically. The default domain is 0&ndash;40 kWh for a
representative household and can be overridden for a reported sensitivity.
The mechanism/counties recipes patch the current commit's
`claims-<sha>.html` (resolved by `current_claims_doc()`, never a hardcoded
filename) in place between HTML-comment markers, so re-running is idempotent
(no duplicated blocks).

## Run metadata

`python3 -m figure_builder all` writes `figures/run_metadata.json` after all
artifacts exist. The manifest records the Git SHA and runtime, hashes the exact
weather/load inputs and output artifacts, and identifies both policy regimes,
capital-cost sources, sweep points, solver assumptions, and utility tariff
source IDs. Values come from the same primitives used by the sweep rather than
being copied into a parallel configuration.

The manifest also hashes the exact claims-only EAC table assembled from the
Step 18 accounting primitives and its sidecar source receipt. The receipt records the model Git SHA,
the exact billing-output timestamp for each scenario, the three scenario-to-case
mappings, and the 141 SHA-tagged scenario/county completion markers checked
before normalization. The statewide builder requires exactly the declared 47
counties for every case, rejects duplicate or non-finite rows, and constructs
each reported total as the exact sum of its seven cost components. It never
fills a missing scenario/county from another run or from Step 18's broader
sibling-scenario family.

The sweep objective uses hourly import prices, NBT export prices, and ACC Plus.
It does not apply annual net-surplus compensation; the manifest records that
boundary explicitly instead of listing NSC source data as if it affected the
sizing result.

The headline Claim-1 figure is a **before/after** comparison
(`plot_pv_batt_vs_capex_compare`): a 2025 panel (with the 30% federal ITC,
battery `$1,022/kWh` net) beside a current-law panel (ITC expired,
`$1,460.64/kWh` net), on shared axes. The market markers state their resolution:
12x24 for the 2025 sensitivity and 8,760 hours for the current-law exact solve.
`build_mechanism_block` computes both regime sweeps for the county automatically;
the mechanism and ceiling panels are drawn at current law. The four-county grid
(`build_county_grid`) is also before/after: each county is a
2025-vs-current-law comparison, stacked full-width.

## Prices track the policy regime automatically

`live_prices()` reads the current default regime (`POST_ITC_2026`, no federal
ITC → PV `$3,300/kW`, battery `$1,460.64/kWh` net). Figures regenerated today
therefore reflect current law, not the expired `ITC_2025` prices
(`$2,310` / `$1,022`) the original figures were drawn at. The before/after
recipes load both regimes deliberately; callers do not select one implicitly.

## Testing

```bash
python3 -m pytest figure_builder/tests/ -q
```

## Remaining migration boundary

The publication figures for statewide Claims 2 and 3 are now generated here
from the paired Step 18 EAC result table. Other exploratory scenario-comparison
figures still live in `helpers/plot_scenario_comparison_helper.py` (used by
pipeline steps 18–23, the sensitivity runner, and the `experiments/` sweeps) and
in `skills/research-figure-builder/scripts/build_research_figures.py`. They are
outside the Claims 1–3 publication path and have not been migrated.
