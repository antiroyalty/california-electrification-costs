# Superseded Step 9b co-optimization design notes

> This design note predates the shared `tariffs/` package and still describes
> the removed county/climate-zone export-rate path. It is retained as research
> history only. See `NBT_TARIFF_MODEL.md` and the current Step 9b code for the
> authoritative implementation.

This document outlines a new pipeline step that co‑optimizes:
- PV system size (kW)
- Battery size (kWh and kW)
- Hour‑by‑hour dispatch decisions (charge/discharge/splits)

to minimize total annual cost (capital + net energy bill) under time‑varying import prices and NEM 3.0 export credits.

The model is linear and solves either on a 12×24 (288) time‑slice basis or on the full 8760 hours.

## Where It Plugs In

- New step: `step9b_cooptimize_pv_battery.py` (runs after base loads are available and before Step 10/12).
- Inputs:
  - County load and weather (as in Step 9):
    - `data/loadprofiles/<scenario>/<housing>/<county>/combined_profiles_<scenario>_<county>.csv`
    - `data/loadprofiles/<scenario>/<housing>/<county>/weather_TMY_<county>.csv`
  - NEM3 export table via `helpers/nem3_export_rates.get_export_rate_table_for_county('data/NEM3', utility, county)` (CSV‑only source).
  - Retail time‑of‑use plan from `helpers/electricity_rate_helpers` for the county utility.
  - Capital costs (annualization params) from existing helpers/config (e.g., Step 14 or `helpers/capital_cost_map_builder.py`).
- Outputs:
  - Optimized capacities: PV kW, battery kWh, battery kW.
  - Hourly series (8760 or 288 time‑slices expanded) for:
    - `PV AC (kWh)`, `System to Load`, `System to Battery`, `Battery to Load`, `Grid to Load`, `PV to Grid (Exports)` (and optionally `Grid to Battery` if enabled).
  - Aggregator file compatible with Step 12 (`loadprofiles_for_rates_<county>.csv`) including at minimum:
    - `timestamp`
    - `nem3.imports.kwh` and `nem3.exports.kwh` (dispatch‑consistent)
    - `retail.imports.kwh` (if you want retail‑only cost comparison)
  - A small JSON/CSV summary with objective components (import charges, export credits, NBCs, fixed/minimum bills, annualized capex, degradation cost, etc.).

Step 12 then consumes these imports/exports directly; no change needed to Step 12 logic beyond using the new aggregator data.

## Mathematical Program (LP)

### Sets and Indexing
- Hours `h ∈ H` (either 8760 or 288 = 12 months × 24 hours, weighted by days per month).
- Months `m = month(h)` for NEM3 rates, minimum bill, fixed charges, and monthly carry‑forward.

### Parameters
- Load `L[h]` (kWh/h) from combined profiles (Step 3 output).
- Weather PV yield per kW `G[h]` (kWh/kW) from Step 9 weather path (GHI‑based PV AC per 1 kW), after the same shift/alignment used in Step 9.
- Retail import price `p_imp[h]` ($/kWh) from `helpers/electricity_rate_helpers` (TOU by season/day type).
- Non‑bypassable charge `p_nbc` ($/kWh) from NEM3 options (per utility); applied to imports.
- ACC export price `p_exp[h]` ($/kWh) from `helpers/nem3_export_rates` (month×hour table).
- Fixed charge `F_m` ($/month) from plan or options; minimum bill `M_m` ($/month).
- Efficiency: `η_ch`, `η_dis` (default sqrt(RTE)), min/max SOC fractions.
- Capitalization:
  - Annualization factor (CRF) for PV and Storage (based on lifetime and WACC).
  - PV capex $/kW: `c_pv_kw`.
  - Battery capex $/kWh: `c_batt_kwh`; inverter/PCS (optional) $/kW: `c_batt_kw`.
  - Battery degradation cost per throughput kWh: `c_deg` ($/kWh_throughput) = replacement_cost / (usable_kWh × cycles_life). With 1000 cycles, choose usable window (e.g., 70%) when computing.
- Time‑slice weights `w[h]` (days in month for 12×24) or `w[h]=1` for 8760.

### Decision Variables
- Sizing:
  - `PV_kw ≥ 0` (continuous)
  - `B_E_kWh ≥ 0` battery energy capacity
  - `B_P_kW ≥ 0` battery power capacity
- Flows (all ≥ 0):
  - `pv2load[h]`, `pv2batt[h]`, `pv2grid[h]`
  - `batt2load[h]`, optional `batt2grid[h]` (usually 0 under NEM constraints)
  - `grid2load[h]`, optional `grid2batt[h]` (enable if you allow grid charging)
- State of charge:
  - `SOC[h]` (kWh)
- Billing auxiliaries:
  - Monthly energy payment slack `y_m ≥ 0` for `max(0, energy_charge − carry_in − export_credit)`
  - Monthly minimum bill slack `z_m ≥ 0` for `max(0, M_m − (NBC + fixed + y_m)`
  - Monthly credit carry `C_m ≥ 0` ($) (allowed to carry forward per NEM3 rules)

### Constraints
- PV availability split:
  - `pv2load[h] + pv2batt[h] + pv2grid[h] ≤ PV_kw × G[h]`
- Load balance:
  - `pv2load[h] + batt2load[h] + grid2load[h] = L[h]`
- Battery SOC dynamics (hourly):
  - `SOC[h+1] = SOC[h] + η_ch × (pv2batt[h] + grid2batt[h]) − (1/η_dis) × (batt2load[h] + batt2grid[h])`
- SOC limits:
  - `SOC_min = B_E_kWh × SOC_min_frac`
  - `SOC_max = B_E_kWh × SOC_max_frac`
  - `SOC_min ≤ SOC[h] ≤ SOC_max`
- Battery power limits:
  - `pv2batt[h] + grid2batt[h] ≤ B_P_kW`
  - `batt2load[h] + batt2grid[h] ≤ B_P_kW`
- Optional grid charging/export limits:
  - Disallow `grid2batt[h]` (set to 0) if grid charging not permitted.
  - Disallow `batt2grid[h]` (set to 0) if battery‑sourced exports are ineligible.
- Monthly billing linearization:
  - Define monthly energy charge (pre‑NBC) and export credit:
    - `E_m = Σ_{h∈m} w[h] × grid2load[h] × (p_imp[h] − p_nbc)`
    - `NBC_m = Σ_{h∈m} w[h] × grid2load[h] × p_nbc`
    - `X_m = Σ_{h∈m} w[h] × pv2grid[h] × p_exp[h]` (optionally include batt2grid if eligible)
  - Carry‑forward accounting:
    - `y_m ≥ E_m − C_{m−1} − X_m` and `y_m ≥ 0` (monthly energy payment after credits)
    - `C_m ≥ (C_{m−1} + X_m − E_m)` and `C_m ≥ 0` (leftover credits carry to next month)
  - Minimum bill enforcement:
    - `z_m ≥ M_m − (NBC_m + F_m + y_m)` and `z_m ≥ 0`
- Capacity non‑negativity and optional upper bounds.

### Objective (Minimize Annual Total Cost)

```
Minimize:  PV_kw * c_pv_kw * CRF
         + B_E_kWh * c_batt_kwh * CRF
         + B_P_kW * c_batt_kw * CRF  (optional)
         + Σ_m ( NBC_m + F_m + y_m + z_m )
         + c_deg * Σ_h w[h] * (batt2load[h] + batt2grid[h])
```

- Interpretation:
  - Annualized capex via CRF added to annual operating bill.
  - Energy payment `y_m` reflects energy imports net of carried credits; `NBC_m` and fixed `F_m` are always paid.
  - `z_m` captures any minimum‑bill shortfall.
  - Degradation cost proportional to discharge throughput.

This is a linear program (all variables continuous; no binaries), solvable at 8760 scale on a modern laptop. The 12×24 option uses weights `w[h] = days_in_month` to approximate full‑year behavior with 288 time slices.

## Practical Details

- Library: implement with `cvxpy`, `pulp`, or `pyomo`. For an open solver, CBC (via pulp) or ECOS/OSQP (via cvxpy) work well.
- Weather → PV per‑kW series `G[h]`: reuse Step 9’s GHI‑to‑AC conversion so results are consistent.
- NEM3 tables: use `helpers/nem3_export_rates.get_export_rate_table_for_county('data/NEM3', utility, county)`.
- Retail TOU: compute `p_imp[h]` per hour using `helpers/electricity_rate_helpers` (season/day‑type mapping).
- Options: toggle grid charging and battery‑to‑grid; many utilities prohibit credit for non‑PV exports.
- Sizing bounds: add reasonable upper bounds to avoid unbounded capacity (or use capex to implicitly bound).

## “Value of Storage” Reporting

Produce a summary showing:
- Annual bill with co‑optimized dispatch vs. rule‑based Step 9 dispatch
- Export credits earned, energy imports purchased, NBC totals
- Throughput and implied degradation cost paid
- Marginal value of adding 1 kWh battery or 1 kW PV at the optimum (dual values or perturbation runs)

## Files and Interfaces

- New step name: `step9b_cooptimize_pv_battery.py` (CLI similar to Step 9):
  - `--base-input-dir`, `--base-output-dir`, `--scenario`, `--housing-type`, `--counties`, `--timeslices {8760|288}`
  - `--allow-grid-charging`, `--allow-batt-export`, `--plan <rate-plan>` (or iterate plans)
- Outputs per county:
  - `solar_storage_dispatch_profiles_<county>.csv` and `_with_exports_` variant, matching Step 9 column names (for plotting)
  - `loadprofiles_for_rates_<county>.csv` with the aggregator fields used by Step 12:
    - `nem3.imports.kwh`, `nem3.exports.kwh`, `retail.imports.kwh`, `timestamp`
  - `CAPITAL_COSTS/electrified_assets.csv` update (append new PV/Battery sizes), or a parallel file (to avoid overwriting other runs)
  - `results/optimization/summary_<county>.json` with objective components and capacities

## 288 vs 8760

- 288 mode (12 months × 24 hours) is fast and captures monthly NEM3 rates and minimum bills. Use day weights in the objective and monthly sums.
- 8760 mode uses real weather/load chronology (better fidelity for SOC evolution) at higher compute cost.
- Start with 288 for development and regression tests; add 8760 as a switch.

## Extensions

- Multiple retail plans: maximize savings across plans (choose min over plan‑specific objectives), or solve per‑plan and report best.
- Demand charges: add max‑demand auxiliaries if a plan requires them (requires additional linearization but still LP with monthly max variables).
- Net surplus compensation at true‑up: include an NSC term if applicable.
- Stochastic PV or load: robust/recourse variants (beyond current scope; keep LP deterministic for now).

## Validation Plan

- Unit tests on tiny systems (e.g., 3 months × 3 hours) with hand‑computed outcomes.
- Compare against Step 9 rule‑based dispatch on a real county; check that co‑optimize never performs worse (once capex is included appropriately).
- Sanity checks: SOC bounds, energy balances, zero negative flows, monthly accounting identity.

---
Questions welcome. I can scaffold the step with a minimal LP (pulp or cvxpy), wire inputs/outputs, and iterate on plan/rate detail and constraints as we validate.
