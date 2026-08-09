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
| `datasets.py` | Collectors (`collect_*`) that run the model and return tidy DataFrames. |
| `charts.py` | Pure plot functions (`plot_*`): DataFrame → matplotlib Figure. No IO. |
| `docio.py` | Pure string primitives: embed PNGs, patch/splice HTML documents idempotently. |
| `recipes.py` | Compose the above into specific document figures (mechanism block, county grid, bridge, split). |
| `__main__.py` | CLI driver; `all` emits `figures/run_metadata.json`. |
| `tests/` | Unit tests for the pure primitives (`docio`, `pricing`). |

## Usage

The combined doc follows a **one-page-per-commit** convention: recipes target
`claims-<current-sha>.html` (resolved from `git rev-parse --short HEAD`), never a
hardcoded filename, so a prior commit's archived snapshot is never overwritten.
`snapshot` creates the current commit's file (seeded from the most recent
snapshot) if it does not exist yet; `all`/`mechanism`/`counties` seed it
automatically.

```bash
python3 -m figure_builder snapshot                  # ensure claims-<sha>.html exists

# Regenerate everything (sweeps -> figures -> patch combined doc -> split)
python3 -m figure_builder all

# Or step by step:
python3 -m figure_builder sweeps                    # weighted 12x24 sensitivity sweeps
python3 -m figure_builder sweeps --counties alameda --force
python3 -m figure_builder sweeps --counties alameda --fine  # deliberate 8760 run
python3 -m figure_builder mechanism                 # Claim-1 Figures A/B/C + objective box
python3 -m figure_builder counties                  # Claim-1 four-county grid
python3 -m figure_builder bridge                    # assumption-bridge waterfall PNG
python3 -m figure_builder split                     # combined doc -> claim1/2/3.html
```

Sweeps are cached in `figure_builder/sweeps/` as
`sweep_288_<county>_<regime>.csv` by default, or `sweep_8760_...` with
`--fine` (keyed by regime, since solar's fixed price differs between regimes),
and reused; pass `--force` to recompute. Weighted 12x24 is the declared
sensitivity-grid resolution; use full chronology for headline cases and
targeted checks, not large low-cost grids. The
cache records the explicit battery-capacity bound and solver diagnostics; a
cache generated under a different sizing domain or the former unbounded model
is rejected automatically. The default domain is 0&ndash;40 kWh for a
representative household and can be overridden for a reported sensitivity.
The
mechanism/counties recipes patch `claims-c459506.html` in place between
HTML-comment markers, so re-running is idempotent (no duplicated blocks).

The headline Claim-1 figure is a **before/after** comparison
(`plot_pv_batt_vs_capex_compare`): a 2025 panel (with the 30% federal ITC,
battery `$1,022/kWh` net) beside a current-law panel (ITC expired,
`$1,460.64/kWh` net), on shared axes. `build_mechanism_block` computes both
regime sweeps for the county automatically; the mechanism and ceiling panels are
drawn at current law. The four-county grid (`build_county_grid`) is also
before/after: each county is a 2025-vs-current-law comparison, stacked
full-width.

## Prices track the policy regime automatically

`live_prices()` reads the current default regime (`POST_ITC_2026`, no federal
ITC → PV `$3,300/kW`, battery `$1,460.64/kWh` net). Figures regenerated today
therefore reflect current law, not the expired `ITC_2025` prices
(`$2,310` / `$1,022`) the original figures were drawn at. To render the
before/after comparison, pass a regime through the recipes:

```python
from appliances.incentive_policy import PolicyRegime
from figure_builder.recipes import build_mechanism_block
build_mechanism_block(regime=PolicyRegime.ITC_2025)
```

## Testing

```bash
python3 -m pytest figure_builder/tests/ -q
```

## Not yet migrated

The scenario-comparison figures still live in
`helpers/plot_scenario_comparison_helper.py` (used by pipeline steps 18–23, the
sensitivity runner, and the `experiments/` sweeps) and in
`skills/research-figure-builder/scripts/build_research_figures.py`. Folding those
`collect_*` / `plot_*` functions into this package — behind a re-export shim so
the existing importers keep working — is the planned second step.
