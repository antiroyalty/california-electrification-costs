• Here are the most useful diagnostics/plots to determine whether “battery = 0” is correct or a modeling/input issue.

  Quick sanity checks (printouts)

  - Annual load kWh, annual PV per‑kW kWh, and chosen PV size.
      - If PV size is 0, battery will almost always be 0 when allow_grid_charging=False.
  - Check that load_kwh isn’t all zeros and G (PV per‑kW) isn’t all zeros.
  - Confirm p_imp and p_exp are in $/kWh and not accidentally reversed or scaled.

  Plots that immediately reveal whether battery has value

  1. Import vs export prices over the year (time series + histograms).
     If p_exp is often close to or above p_imp, there’s little reason to store PV.
  2. PV per‑kW vs Load (hourly overlay for a representative week + monthly averages).
     If PV rarely exceeds load, there’s no surplus to store.
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
