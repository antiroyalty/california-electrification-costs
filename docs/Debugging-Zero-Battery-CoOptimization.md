• Here are the most useful diagnostics/plots to determine whether “battery = 0” is correct or a modeling/input issue.

  Quick sanity checks (printouts)

  - Annual load kWh, annual PV per‑kW kWh, and chosen PV size.
      - If PV size is 0, battery will almost always be 0 when allow_grid_charging=False.
  - Check that load_kwh isn’t all zeros and G (PV per‑kW) isn’t all zeros.
  - Confirm p_imp and p_exp are in $/kWh and not accidentally reversed or scaled.

  Prices are: 

  $   python3 -m pipeline.steps.step9b_cooptimize_pv_battery \
    --scenario baseline_coopt \
    --housing-type single-family-detached \
    --counties alameda \
    --debug-prices
[step9b] Price stats for alameda (import min/median/max=$0.000/0.463/0.607, export min/median/max=$0.000/0.053/0.081)
[step9b] alameda: PV=1.51 kW, Battery=0.00 kWh

Import is much greater than export, so they don't appear reversed. Is the export compensation accurate and real? Yes, that's consistent with NEM3.

 python3 scripts/debug_coopt_battery_diagnostics.py \
    --scenario baseline_coopt \
    --housing-type single-family-detached \
    --county alameda
=== Co-opt PV/Battery Diagnostics ===
Dispatch CSV: data/loadprofiles/baseline_coopt/single-family-detached/alameda/solar_storage_dispatch_profiles_alameda.csv
Annual Load (kWh): 5,558.5
Annual PV AC (kWh): 2,188.2
Annual PV to Load (kWh): 1,296.2
Annual PV to Battery (kWh): 0.0
Annual PV to Grid (kWh): 892.0
Hours with PV to Grid > 0: 2328
Max PV to Grid hour (kWh): 1.117
Annual PV surplus (kWh): 0.0
Annual PV used onsite (kWh): 1,296.2
Annual Grid to Load (kWh): 4,262.2
Wrote plot: data/loadprofiles/baseline_coopt/single-family-detached/alameda/coopt_battery_debug_alameda.png

  Plots that immediately reveal whether battery has value

  1. Import vs export prices over the year (time series + histograms).
     If p_exp is often close to or above p_imp, there’s little reason to store PV.

But it's not. The export price is much lower than the import price, so there should be reason to store the PV.

  2. PV per‑kW vs Load (hourly overlay for a representative week + monthly averages).
     If PV rarely exceeds load, there’s no surplus to store.

Here's what's happening. The LP compares annualized battery cost vs the actual arbitrage value of shifting PV exports:

  - Upper bound on annual savings if you could shift all exports:
    892 kWh × (0.463 − 0.053) × 0.96 ≈ $350/year
    (and that’s optimistic: actual savings will be lower because surplus happens when imports are often cheaper.)
  - Annualized battery cost per kWh is high:
    800 $/kWh × CRF(7%,15y) ≈ 800 × 0.109 = $87/year per kWh
    So a 4 kWh battery costs ~$350/year, roughly matching the maximum possible savings.

  Given partial cycling and SOC limits, the model can easily conclude battery value < annualized cost, so 0 kWh is optimal.

  Probably not a bug, but should confirm with a few sensitivity checks:
  - Make battery very cheap:
  => If battery stays 0, then there is likely a modeling assumption issue or very low arbitrage value.

  python3 -m pipeline.steps.step9b_cooptimize_pv_battery \
      --scenario baseline_coopt \
      --housing-type single-family-detached \
      --counties alameda \
      --batt-capex-kwh 50
  [step9b] alameda: PV=2.88 kW, Battery=21.22 kWh

  Sooo our battery size shot up! This suggests an "issue" with how we price the battery, and it's worth checking the assumptions. It may also be worth checking the assumptions of solar?

  - Allow grid charging:
  => If battery becomes >0 only then, it means PV surplus alone isn’t enough to justify storage.

  - Also need to check price spread during export hours
  => Compare import price at the time exports happen vs export credit at those hours. If import prices are often low at those times, the arbitrage value is much smaller than the median import price.

  3. PV surplus vs export credit (scatter or heatmap).
     Shows whether surplus occurs when export credits are low (battery helpful) or high (battery less useful).
  4. Arbitrage value per kWh stored:
     For each hour with PV surplus, compute max_future_import_price - export_credit_now (optionally adjusted for round‑trip efficiency and degradation). If this is rarely positive or very small, battery should be
     zero.
  5. SOC/flows in a forced‑battery run (see “sensitivity runs” below).
     If the battery never charges even when forced, the model or assumptions are likely off.

  Derived diagnostics (numbers)

  - annual_import_cost, annual_export_credit, annual_capex, annual_degradation (already stored now).
  - Value of 1 kWh of storage:
    Estimate annual savings per kWh of storage (from arbitrage) vs annualized battery cost per kWh.
    If savings < cost, 0 kWh is correct.

  Sensitivity runs to prove it

  - Force a minimum battery (e.g., B_E >= 1 kWh or >= 5 kWh) and see if it actually cycles.
    If it doesn’t, then price signals or surplus don’t justify it.
  - Drop battery capex to a very low value (e.g., batt_capex_per_kwh=10) and see if it becomes >0.
    If still 0, then there’s no arbitrage opportunity given constraints.
  - Allow grid charging temporarily.
    If battery becomes non‑zero only then, it indicates PV surplus is insufficient and grid arbitrage is the only incentive.

  Potential modeling reasons battery is always 0

  - PV size is 0 (or too small), so there’s no PV surplus to store.
  - Export credit is high relative to import price, so exporting is better than storing.
  - Battery capex is too high relative to annual savings.
  - Degradation cost set too high (if non‑zero).
  - Load or PV series are misaligned or flat.

  If you want, I can add a small debug script that produces these plots for a specific county/scenario and a forced‑battery sensitivity run. Just tell me which scenario/county you want to inspect.
