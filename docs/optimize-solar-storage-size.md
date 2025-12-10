# Solar + Storage Size Optimization (Explicit, NEM3-Aware)

Goal: choose PV size (kW) and battery energy capacity (kWh) that minimize annual cost, with NEM 3.0 export crediting and the best retail import plan for the county’s utility. This replaces sweep‑based search with a direct optimization that calls the existing simulation + billing pipeline.

## Scope and Outcomes

- Variables to optimize: `solar_kw` (continuous, kW AC at inverter output) and `battery_kwh` (continuous, kWh usable energy).
- Objective: minimize total annualized cost of ownership (aka EAC) with PV + storage under NEM3, choosing the best import rate plan (E‑TOU‑C/D or utility equivalent).
- Constraints: bounds on decision variables, e.g. `0 ≤ solar_kw ≤ PV_KW_MAX`, `0 ≤ battery_kwh ≤ BATTERY_KWH_MAX`.
- Outputs per county: best import plan, optimal sizes `(solar_kw*, battery_kwh*)`, and minimized annual costs broken down (imports, export credits, NBCs, fixed charges, annualized capex).

This optimization uses the existing Step 9 (flows) + Step 12 (billing) functions; only a thin “optimizer” wrapper is added.

## Objective Function (EAC) and Equations

For a given county, scenario, and import plan `p` (NEM3 export crediting always applied):

1) Dispatch → flows (Step 9):
   - Input: `solar_kw`, `battery_kwh`, hourly load `L_t`, weather `W_t`, dispatch parameters (efficiencies, power limits, SOC bounds).
   - Output (8760): imports `Imp_t`, exports `Exp_t`.

2) Rate plan and NEM3 costs (Step 12):
   - Import energy charge: `C_imp = Σ_t Imp_t · r_p(t)` where `r_p(t)` is hourly retail import rate for plan `p`.
   - Non‑bypassable charges (NBC): `C_nbc = Σ_t Imp_t · nbc_rate`.
   - ACC export credit: monthly carry‑forward credit under NEM3:
     - Per‑hour credit: `credit_t = Exp_t · acc(month(t), hour(t))`.
     - Monthly net: export credits offset only energy charges; unspent credit carries to next month (Step 12 already implements this). Denote annual sum of credited amount as `C_exp` (dollars).
   - Fixed/minimum charges: `C_fixed`, `C_min` per month (use plan defaults or Step 12 options).
   - Net electric bill (NEM3): `Bill_NEM3 = Σ_month max(C_energy_net + C_nbc + C_fixed, C_min)` where `C_energy_net` = (monthly energy charges) − (monthly export credits + carry‑in). See Step 12’s `calculate_nem3_annual_costs` for exact accounting.

3) Annualized capital costs (CRF annuity):

   - Capital recovery factor: `CRF(r, N) = r (1+r)^N / ((1+r)^N − 1)` where `r` is discount rate, `N` lifetime (years).
   - PV annualized: `Cap_PV = CRF(r, N_pv) · (Capex_PV_per_kW · solar_kw − Incentives_PV) + OandM_PV_per_kW · solar_kw`.
   - Battery annualized: `Cap_Batt = CRF(r, N_batt) · (Capex_Batt_per_kWh · battery_kwh − Incentives_Batt) + OandM_Batt_per_kWh · battery_kwh`.

4) Total objective for plan `p`:

```
EAC_p(solar_kw, battery_kwh) = Bill_NEM3_p + Cap_PV + Cap_Batt
```

We minimize `EAC_p` over `(solar_kw, battery_kwh)` with bounds. We repeat for all import plans `p` in the county’s utility and select the global minimum.

Notes
- Gas costs and non‑PV capital items do not change with `(solar_kw, battery_kwh)` and can be added back if needed; they do not affect the argmin.
- This formulation uses hourly simulation → monthly billing for NEM3 (credits carry forward), matching Step 12.

## Key Variables and Parameters

Decision variables
- `solar_kw` (float, kW): PV system AC size. Bounds e.g. `[0, 2·PV_kW_match]`.
- `battery_kwh` (float, kWh): usable battery energy. Bounds e.g. `[0, 30]`.

Dispatch parameters (from Step 9 core)
- Efficiencies: `eta_charge`, `eta_discharge` (from `ROUND_TRIP_EFFICIENCY`).
- Power limits: `P_CHARGE_MAX_KW`, `P_DISCHARGE_MAX_KW`.
- SOC bounds: `MIN_SOC_FRAC`, `MAX_SOC_FRAC`.
- Strategy: dynamic PV‑only charging, evening discharge (only mode used).

Rates and options (from helpers)
- Import plans per utility: `helpers.electricity_rate_helpers` (PG&E, SCE, SDG&E).
- NEM3 export ACC tables: `helpers.nem3_export_rates.py`. Use `get_export_rate_table_for_county`.
- NEM3 options: NBC $/kWh, fixed charges, minimum bill, true‑up month (see `NEM3Options`).

Capital cost inputs
- PV: `Capex_PV_per_kW`, `OandM_PV_per_kW`, `Incentives_PV`, `N_pv`.
- Battery: `Capex_Batt_per_kWh`, `OandM_Batt_per_kWh`, `Incentives_Batt`, `N_batt`.
- Discount rate: `r`.

Data
- Hourly load `L_t` (Step 7) and weather `W_t` (TMY) per county.
- All flows are 8760 hourly points.

## Software Approach

We implement a small optimizer that reuses existing pipeline pieces:

1) Flows simulator (Step 9 core)
   - Use `step9_solar_storage_dispatch_core.pv_timeseries_ac_kwh(...)` and `battery_dispatch_dynamic(...)`.
   - Accept `solar_kw` directly (skip heuristic sizing) and set `battery_kwh` via the provided context manager.
   - Produce hourly `imports` and `exports` (PV‑only under current dispatch; battery export can be added later).

2) Billing (Step 12)
   - Use `calculate_nem3_annual_costs(...)` for NEM3 (imports, exports, CBS/NBC/fixed/min flows).
   - For each candidate import plan `p`, compute `Bill_NEM3_p`.

3) Capital costs
   - Compute `CRF` and `Cap_PV`, `Cap_Batt` from configured capex/O&M/lifetimes/discount rate (same source used in Steps 12–15).

4) Objective wrapper

```python
def evaluate_eac_for_plan(solar_kw, battery_kwh, plan, county_ctx) -> float:
    imports, exports = simulate_flows(solar_kw, battery_kwh, county_ctx)
    bill = calculate_nem3_bill(imports, exports, plan, county_ctx)
    cap = annualized_capex(solar_kw, battery_kwh, county_ctx)
    return bill + cap
```

5) Optimization algorithm
- 2D black‑box (non‑smooth) → use a robust derivative‑free search.
- Options (pick one):
  - SciPy `optimize.minimize` with `method='Powell'` or `method='Nelder-Mead'` + bounds.
  - SciPy `dual_annealing` (global) then `Powell` (local) refine.
  - Pure‑Python coordinate descent with 1D golden‑section searches over `solar_kw` and `battery_kwh` alternately until convergence (no external deps).

Recommended (simple + reliable): coordinate descent
1. Initialize `(solar_kw, battery_kwh)` (e.g., `(0.5·PV_match, 13.5)`)
2. Optimize `solar_kw` on `[0, PV_KW_MAX]` holding `battery_kwh` fixed via golden‑section.
3. Optimize `battery_kwh` on `[0, BATTERY_KWH_MAX]` holding `solar_kw` fixed via golden‑section.
4. Repeat 2–3 until size changes < tolerance or max iters.
5. Try a few restarts (e.g., battery_kwh in {0, 7, 13.5, 20}) and keep the best.

For each plan `p` in the county’s utility, run the optimizer and keep the best `(solar_kw*, battery_kwh*, EAC_p*)`. The global answer is the lowest `EAC_p*` across plans.

## Pseudocode

```python
from step9_solar_storage_dispatch_core import (
    pv_timeseries_ac_kwh, battery_dispatch_dynamic, temp_battery_capacity_kwh
)
from step12_evaluate_electricity_rates import calculate_nem3_annual_costs

def simulate_flows(solar_kw, battery_kwh, county_ctx):
    weather, load = county_ctx.weather_df, county_ctx.load_kwh
    pv = pv_timeseries_ac_kwh(weather, solar_kw)
    with temp_battery_capacity_kwh(battery_kwh):
        grid_demand, batt_charge, batt_discharge, grid_to_load, grid_to_batt, pv_to_batt, soc = \
            battery_dispatch_dynamic(load, pv)
    system_to_load = [min(p, l) for p, l in zip(pv, load)]
    pv_exports = [max(0.0, p - a - b) for p, a, b in zip(pv, system_to_load, pv_to_batt)]
    imports = [gl + gb for gl, gb in zip(grid_to_load, grid_to_batt)]
    return imports, pv_exports

def annualized_capex(solar_kw, battery_kwh, capex, oam, incentives, lifetimes, r):
    def crf(r, n):
        return r * (1+r)**n / ((1+r)**n - 1)
    cap_pv   = crf(r, lifetimes.pv)   * max(0.0, capex.pv_per_kw * solar_kw - incentives.pv)   + oam.pv_per_kw * solar_kw
    cap_batt = crf(r, lifetimes.batt) * max(0.0, capex.batt_per_kwh * battery_kwh - incentives.batt) + oam.batt_per_kwh * battery_kwh
    return cap_pv + cap_batt

def calculate_nem3_bill(imports, exports, plan, county_ctx):
    ts = county_ctx.timestamps
    opts = county_ctx.nem3_options
    export_table = county_ctx.acc_table  # from helpers.nem3_export_rates
    return calculate_nem3_annual_costs(ts, imports, exports, county_ctx.utility, plan, options=opts, export_table=export_table)[plan]

def eac_for_plan(x, plan, county_ctx):
    solar_kw, battery_kwh = x
    imports, exports = simulate_flows(solar_kw, battery_kwh, county_ctx)
    bill = calculate_nem3_bill(imports, exports, plan, county_ctx)
    cap  = annualized_capex(solar_kw, battery_kwh, county_ctx.capex, county_ctx.oam, county_ctx.incentives, county_ctx.lifetimes, county_ctx.discount_rate)
    return bill + cap

def optimize_for_plan(plan, bounds, county_ctx):
    # coordinate descent with golden‑section subroutines, or SciPy minimize
    best_x, best_val = None, float('inf')
    for b0 in [0.0, 7.0, 13.5, 20.0]:
        x = [min(bounds.solar_kw[1], 0.5*county_ctx.pv_kw_match), min(bounds.battery_kwh[1], b0)]
        # alternate optimize solar, then battery; break when changes are tiny
        # (omitted here for brevity)
        val = eac_for_plan(x, plan, county_ctx)
        if val < best_val:
            best_x, best_val = x, val
    return best_x, best_val

def run_optimizer(county_ctx):
    plans = county_ctx.import_plans  # e.g., ["E-TOU-C", "E-TOU-D", ...]
    results = {}
    for p in plans:
        x_p, val_p = optimize_for_plan(p, county_ctx.bounds, county_ctx)
        results[p] = {"x": x_p, "eac": val_p}
    # choose global best over plans
    best_plan = min(results, key=lambda k: results[k]["eac"]) if results else None
    return best_plan, results
```

## Bounds and Initialization

- `PV_KW_MAX`: e.g., `2.0 × PV_kW_match` where `PV_kW_match` is the PV size that annual‑matches the load (`Σ L_t / (PR × annual_irradiance × eff)`); compute once per county from weather.
- `BATTERY_KWH_MAX`: e.g., 30–40 kWh default upper bound.
- Start from `(0.5 × PV_kW_match, 13.5 kWh)` and a few battery restarts: `{0, 7, 13.5, 20}`.

## Libraries and Code Modules

Internal modules (already in repo)
- `step9_solar_storage_dispatch_core`: PV model + dynamic dispatch (flows).
- `step12_evaluate_electricity_rates`: `calculate_nem3_annual_costs` for NEM3 billing.
- `helpers.electricity_rate_helpers`: utility rate plans (PG&E, SCE, SDG&E).
- `helpers.nem3_export_rates`: ACC export rate tables; `NEM3Options`.

External libraries
- `pandas`, `numpy` (arrays and time series).
- Optional: `scipy` (`scipy.optimize`) if choosing Powell/Nelder‑Mead/global annealing. If unavailable, implement coordinate descent + golden‑section in pure Python.

## Integration Plan

1) Add `step9_optimize_solar_storage.py` (new step):
   - Accept `--scenario`, `--housing-type`, `--counties`.
   - For each county: build a context (load/weather, utility and plans, NEM3 options, capex inputs and CRF params, bounds), run the optimizer, and write `optimized_sizes_<county>.csv` with columns: `[plan, solar_kw, battery_kwh, eac_total, bill_nem3, capex_annual_pv, capex_annual_batt]`.

2) Optionally cache per‑evaluation flows/bills to speed up repeated calls during optimization.

3) Update Step 22 to read `optimized_sizes_*.csv` and display the chosen `(solar_kw*, battery_kwh*)` in a new “Optimized Sizes (NEM3)” card.

4) (Optional) Add CLI flags to Step 12 to compute results directly from aggregator vs. series passed in memory for speed and testability.

## Notes and Extensions

- Battery export: current dispatch does not export battery energy; once implemented, the exports series should include both PV and battery exports for NEM3 credits.
- Demand charges: if any plans include demand components, extend Step 12 to include demand windows in `_hourly_import_rate` and monthly max kW tracking.
- Robustness: include soft penalties or clipping if dispatch results violate bounds; ensure all series are 8760 hourly points.

## Inputs and Outputs (Step 9 Optimizer)

Inputs
- CLI arguments
  - `--base-input-dir` (default `data/loadprofiles`)
  - `--base-output-dir` (present for symmetry; writes occur next to inputs)
  - `--scenario` (e.g., `baseline`)
  - `--housing-type` (e.g., `single-family-detached`)
  - `--counties` (optional list; defaults to all counties in scenario path)
  - Financial parameters (optional; defaults provided)
    - `--discount-rate`, `--pv-capex-per-kw`, `--batt-capex-per-kwh`
    - `--pv-oam-per-kw`, `--batt-oam-per-kwh`
    - `--pv-incentive`, `--batt-incentive`
    - `--pv-life`, `--batt-life`
  - Bounds
    - `--pv-kw-max-multiplier` → PV upper bound = multiplier × PV-match size
    - `--batt-kwh-max` → battery upper bound in kWh
- Required data files
  - Weather (per county): `data/loadprofiles/<scenario>/<housing_type>/<county_slug>/weather_TMY_<county_slug>.csv`
  - Load (per county):    `data/loadprofiles/<scenario>/<housing_type>/<county_slug>/combined_profiles_<scenario>_<county_slug>.csv`
- Internal helpers (no user action)
  - Utility → import plans: `helpers/electricity_rate_helpers`
  - NEM3 export rates: `helpers/nem3_export_rates` (ACC tables and `NEM3Options`)
  - Utility lookup: `helpers.utility_helpers.get_utility_for_county`
- Optional library
  - SciPy (`scipy.optimize`) for global + local continuous optimization; code falls back to a pure-Python search if unavailable.

Outputs
- Per-county results CSV: `data/loadprofiles/<scenario>/<housing_type>/<county_slug>/optimized_sizes_<county_slug>.csv`
  - One row per eligible import plan for the county’s utility.
  - Columns:
    - `plan`: plan name (e.g., `E-TOU-C`)
    - `solar_kw`: optimal PV size (kW AC)
    - `battery_kwh`: optimal battery usable energy (kWh)
    - `eac_total`: minimized annualized total cost ($/year)
    - `bill_nem3`: annual electric bill with NEM3 ($/year)
    - `capex_annual_pv`: annualized PV cost ($/year)
    - `capex_annual_batt`: annualized battery cost ($/year)
    - `best`: boolean flag for the globally best plan/size
- Programmatic return (from `process(...)`): list of written file paths
