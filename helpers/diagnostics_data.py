import os
from typing import Optional

import pandas as pd

from evaluations.incentives import apply_pv_storage_incentives
from evaluations.npv import compute_npv_details_from_inputs
from helpers.main_helpers import slugify_county_name
from helpers.maps_helpers import get_latest_csv_file


def read_total_annual_cost(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
    *,
    with_solar: bool = False,
) -> Optional[float]:
    if with_solar:
        results_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug, "results", "solarstorage")
        row_name = f"{scenario}.solarstorage"
    else:
        results_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug, "results", "totals")
        row_name = scenario
    if not os.path.isdir(results_dir):
        return None
    try:
        path = get_latest_csv_file(results_dir, f"RESULTS_total_annual_costs_{county_slug}_")
        df = pd.read_csv(path, index_col="scenario")
        if row_name not in df.index:
            return None
        row = df.loc[row_name]
        vals = pd.to_numeric(row, errors="coerce").dropna()
        if vals.empty:
            return None
        return float(vals.iloc[0])
    except Exception:
        return None


def pv_storage_net_capex(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
    *,
    incentive: str = "full_incentives",
) -> Optional[float]:
    cap_dir = os.path.join(base_input_dir, "capital_costs")
    fname = f"capital_costs_summary_with_pv_{scenario}_{housing_type.replace('-', '_')}.csv"
    path = os.path.join(cap_dir, fname)
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
        if df.empty or "county_slug" not in df.columns:
            return None
        row = df[df["county_slug"].str.lower() == county_slug]
        if row.empty:
            return None
        pv_capex = float(row.iloc[0].get("pv_capex", 0.0))
        st_capex = float(row.iloc[0].get("storage_capex", 0.0))
        pv_inc_full = float(row.iloc[0].get("pv_incentives_full", 0.0))
        st_inc_full = float(row.iloc[0].get("storage_incentives_full", 0.0))
        pv_net, st_net = apply_pv_storage_incentives(
            pv_capex,
            st_capex,
            pv_incentives_full=pv_inc_full,
            storage_incentives_full=st_inc_full,
            incentive=incentive,
        )
        return float(pv_net + st_net)
    except Exception:
        return None


def electrification_net_capex(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
    *,
    incentive: str = "full_incentives",
) -> Optional[float]:
    cap_dir = os.path.join(base_input_dir, "capital_costs")
    fname = f"capital_costs_{scenario}_{housing_type.replace('-', '_')}.csv"
    path = os.path.join(cap_dir, fname)
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
        if df.empty:
            return None
        if "county_slug" not in df.columns or "net_cost" not in df.columns:
            return None
        sub = df[df["county_slug"].str.lower() == county_slug]
        if "incentive_scenario" in sub.columns:
            sub["incentive_scenario"] = sub["incentive_scenario"].str.lower()
            sub = sub[sub["incentive_scenario"] == (incentive or "").lower()]
        if sub.empty:
            return None
        if "appliance_category" in sub.columns:
            sub = sub[sub["appliance_category"] == "electric"]
        if "appliance_type" in sub.columns:
            sub = sub[~sub["appliance_type"].isin(["solar", "storage"])]
        if sub.empty:
            return None
        vals = pd.to_numeric(sub["net_cost"], errors="coerce").dropna()
        if vals.empty:
            return None
        return float(vals.sum())
    except Exception:
        return None


def compute_npv_details(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
    *,
    horizon_years: int = 25,
    discount_rate: float = 0.07,
    incentive: str = "full_incentives",
) -> Optional[dict]:
    baseline_cost = read_total_annual_cost(
        base_input_dir, "baseline", housing_type, county_slug, with_solar=False
    )
    scenario_cost = read_total_annual_cost(
        base_input_dir, scenario, housing_type, county_slug, with_solar=False
    )
    scenario_solar_cost = read_total_annual_cost(
        base_input_dir, scenario, housing_type, county_slug, with_solar=True
    )
    if baseline_cost is None or scenario_cost is None or scenario_solar_cost is None:
        return None

    pv_storage_net = pv_storage_net_capex(
        base_input_dir, scenario, housing_type, county_slug, incentive=incentive
    )
    electrification_net = electrification_net_capex(
        base_input_dir, scenario, housing_type, county_slug, incentive=incentive
    )
    if pv_storage_net is None:
        return None

    try:
        return compute_npv_details_from_inputs(
            baseline_cost=baseline_cost,
            scenario_cost=scenario_cost,
            scenario_solar_cost=scenario_solar_cost,
            pv_storage_net_capex=pv_storage_net,
            electrification_net_capex=electrification_net,
            horizon_years=horizon_years,
            discount_rate=discount_rate,
        )
    except Exception:
        return None


def read_coopt_capacities(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> Optional[dict]:
    """Read co-optimization sizes and flags from the Step 9b capacity CSV if present."""
    try:
        cap_csv = os.path.join(base_input_dir, scenario, housing_type, "CAPITAL_COSTS", "electrified_assets.csv")
        if not os.path.exists(cap_csv):
            return None
        df = pd.read_csv(cap_csv)
        if df.empty:
            return None

        def to_slug(x):
            try:
                return slugify_county_name(str(x))
            except Exception:
                return str(x)

        row = None
        if "County" in df.columns:
            for _, r in df.iterrows():
                if to_slug(r["County"]) == county_slug:
                    row = r
                    break
        if row is None:
            first_col = df.columns[0]
            for _, r in df.iterrows():
                if to_slug(r[first_col]) == county_slug:
                    row = r
                    break
        if row is None:
            return None

        out = {
            "solar_kw": None,
            "battery_kwh": None,
            "allow_grid_charging": None,
            "allow_batt_export": None,
        }
        if "Solar Capacity (kW)" in row:
            try:
                out["solar_kw"] = float(row["Solar Capacity (kW)"])
            except Exception:
                pass
        if "Battery Capacity (kWh)" in row:
            try:
                out["battery_kwh"] = float(row["Battery Capacity (kWh)"])
            except Exception:
                pass
        if "Allow Grid Charging" in row:
            out["allow_grid_charging"] = bool(row["Allow Grid Charging"]) if not pd.isnull(row["Allow Grid Charging"]) else None
        if "Allow Battery Export" in row:
            out["allow_batt_export"] = bool(row["Allow Battery Export"]) if not pd.isnull(row["Allow Battery Export"]) else None
        return out
    except Exception:
        return None


def sam_csv_path(base_input_dir: str, scenario: str, housing_type: str, county_slug: str) -> Optional[str]:
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    a = os.path.join(county_dir, f"solar_storage_dispatch_profiles_{county_slug}.csv")
    b = os.path.join(county_dir, f"solar_storage_dispatch_profiles_{scenario}_{county_slug}.csv")
    if os.path.exists(a):
        return a
    if os.path.exists(b):
        return b
    return None


def pv_annual_kwh(base_input_dir: str, scenario: str, housing_type: str, county_slug: str) -> float:
    path = sam_csv_path(base_input_dir, scenario, housing_type, county_slug)
    if not path:
        return 0.0
    try:
        df = pd.read_csv(path)
        pvl = pd.to_numeric(df.get("System to Load", pd.Series([0])), errors="coerce").fillna(0.0).sum()
        pvb = pd.to_numeric(df.get("System to Battery", pd.Series([0])), errors="coerce").fillna(0.0).sum()
        return float(pvl + pvb)
    except Exception:
        return 0.0


def pv_net_capex(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
    *,
    incentive: str = "full_incentives",
) -> float:
    cap_dir = os.path.join(base_input_dir, "capital_costs")
    fname = f"capital_costs_summary_with_pv_{scenario}_{housing_type.replace('-', '_')}.csv"
    path = os.path.join(cap_dir, fname)
    if not os.path.exists(path):
        return 0.0
    try:
        df = pd.read_csv(path)
        row = df[df["county_slug"].str.lower() == county_slug]
        if row.empty:
            return 0.0
        pv_capex = float(row.iloc[0].get("pv_capex", 0.0))
        pv_inc_full = float(row.iloc[0].get("pv_incentives_full", 0.0)) if "pv_incentives_full" in row.columns else 0.0
        inc = (incentive or "").lower()
        if inc == "full_incentives":
            return pv_capex - pv_inc_full
        if inc == "half_incentives":
            return pv_capex - (pv_inc_full * 0.5)
        return pv_capex
    except Exception:
        return 0.0


def infer_pv_size_kw_from_csv(csv_path: str) -> Optional[float]:
    """Try to infer PV system size (kW) from the solar+storage CSV header."""
    try:
        if not os.path.exists(csv_path):
            return None
        df_head = pd.read_csv(csv_path, nrows=1)
        candidates = [
            "pv system size",
            "pv size",
            "pv capacity",
            "system size",
            "pv_kw",
            "pv kw",
            "pv (kw)",
            "system capacity",
        ]
        chosen = None
        for col in df_head.columns:
            low = str(col).lower()
            if any(c in low for c in candidates):
                chosen = col
                break
        if chosen is None:
            return None
        val = df_head.iloc[0][chosen]
        try:
            size_kw = float(val)
            if size_kw >= 0:
                return size_kw
        except Exception:
            return None
    except Exception:
        return None
    return None


def lookup_pv_size_kw(
    base_input_dir: str, scenario: str, housing_type: str, county_slug: str
) -> Optional[float]:
    """Find PV size (kW) for a county from Step 9 capacity summary, falling back to CSV header."""
    try:
        cap_csv = os.path.join(
            base_input_dir, scenario, housing_type, "CAPITAL_COSTS", "electrified_assets.csv"
        )
        if os.path.exists(cap_csv):
            try:
                df = pd.read_csv(cap_csv)
                county_col = None
                for c in df.columns:
                    if str(c).strip().lower() in ("county", "county_slug"):
                        county_col = c
                        break
                if county_col is not None:
                    df_idx = df.set_index(county_col)
                else:
                    df_idx = df

                def to_slug(x):
                    try:
                        return slugify_county_name(str(x))
                    except Exception:
                        return str(x)

                df_idx = df_idx.copy()
                df_idx["__slug__"] = [to_slug(x) for x in (df_idx.index if county_col is None else df_idx.index)]
                if "__slug__" not in df_idx.columns:
                    df_idx["__slug__"] = [to_slug(x) for x in df_idx.index]
                row = df_idx[df_idx["__slug__"] == county_slug]
                if row.empty and county_col is not None:
                    row = df[df[county_col] == county_slug]
                if not row.empty:
                    cap_col = None
                    for c in row.columns:
                        low = str(c).lower()
                        if "solar capacity" in low and "kw" in low:
                            cap_col = c
                            break
                        if low in ("solar capacity (kwh)"):
                            continue
                    if cap_col is not None:
                        val = float(row.iloc[0][cap_col])
                        return val
            except Exception:
                pass
        county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
        sam_file = os.path.join(county_dir, f"solar_storage_dispatch_profiles_{county_slug}.csv")
        if not os.path.exists(sam_file):
            alt = os.path.join(county_dir, f"solar_storage_dispatch_profiles_{scenario}_{county_slug}.csv")
            sam_file = alt if os.path.exists(alt) else sam_file
        return infer_pv_size_kw_from_csv(sam_file)
    except Exception:
        return None


def compute_key_metrics(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> Optional[dict]:
    """Compute key metrics with and without solar+storage from Step 9 output."""
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    sam_file = os.path.join(county_dir, f"solar_storage_dispatch_profiles_{county_slug}.csv")
    if not os.path.exists(sam_file):
        alt = os.path.join(county_dir, f"solar_storage_dispatch_profiles_{scenario}_{county_slug}.csv")
        sam_file = alt if os.path.exists(alt) else sam_file
    if not os.path.exists(sam_file):
        return None
    try:
        df = pd.read_csv(sam_file)
        load_col = None
        grid_to_load_col = None
        for col in df.columns:
            low = str(col).lower()
            if load_col is None and "load profile" in low:
                load_col = col
            if grid_to_load_col is None and ("grid to load" in low or ("grid" in low and "load" in low)):
                grid_to_load_col = col
        if load_col is None:
            for col in df.columns:
                if pd.api.types.is_numeric_dtype(df[col]):
                    load_col = col
                    break
        annual_load_kwh = float(pd.to_numeric(df[load_col], errors="coerce").fillna(0.0).sum()) if load_col else None
        grid_with_kwh = (
            float(pd.to_numeric(df[grid_to_load_col], errors="coerce").fillna(0.0).sum())
            if grid_to_load_col
            else None
        )
        assets = compute_assets_info(base_input_dir, scenario, housing_type, county_slug) or {}
        pv_size_kw = assets.get("Solar Capacity (kW)")
        batt_kwh = assets.get("Battery Capacity (kWh)")
        without = {
            "solar_kw": 0.0 if annual_load_kwh is not None else None,
            "battery_kwh": 0.0 if annual_load_kwh is not None else None,
            "annual_load_kwh": annual_load_kwh,
            "grid_to_load_kwh": annual_load_kwh,
        }
        with_vals = {
            "solar_kw": pv_size_kw,
            "battery_kwh": batt_kwh,
            "annual_load_kwh": annual_load_kwh,
            "grid_to_load_kwh": grid_with_kwh,
        }
        return {"with": with_vals, "without": without}
    except Exception:
        return None


def lookup_battery_capacity_kwh(
    base_input_dir: str, scenario: str, housing_type: str, county_slug: str
) -> Optional[float]:
    """Look up battery capacity (kWh) from the Step 9 capacity summary file."""
    try:
        cap_csv = os.path.join(
            base_input_dir, scenario, housing_type, "CAPITAL_COSTS", "electrified_assets.csv"
        )
        if not os.path.exists(cap_csv):
            return None
        df = pd.read_csv(cap_csv)
        county_col = None
        for c in df.columns:
            if str(c).strip().lower() in ("county", "county_slug"):
                county_col = c
                break
        if county_col is not None:
            df_idx = df.set_index(county_col)
        else:
            df_idx = df

        def to_slug(x):
            try:
                return slugify_county_name(str(x))
            except Exception:
                return str(x)

        df_idx = df_idx.copy()
        df_idx["__slug__"] = [to_slug(ix) for ix in (df_idx.index)]
        row = df_idx[df_idx["__slug__"] == county_slug]
        if row.empty:
            return None
        cap_col = None
        for c in row.columns:
            low = str(c).lower()
            if "battery capacity" in low and "kwh" in low:
                cap_col = c
                break
        if cap_col is None:
            return None
        return float(row.iloc[0][cap_col])
    except Exception:
        return None


def compute_energy_flow_metrics(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> Optional[dict]:
    """Compute detailed energy flow metrics from Step 9 solar+storage CSV."""
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    sam_file = os.path.join(county_dir, f"solar_storage_dispatch_profiles_{county_slug}.csv")
    if not os.path.exists(sam_file):
        alt = os.path.join(county_dir, f"solar_storage_dispatch_profiles_{scenario}_{county_slug}.csv")
        sam_file = alt if os.path.exists(alt) else sam_file
    if not os.path.exists(sam_file):
        return None

    try:
        df = pd.read_csv(sam_file)

        def num(col: str) -> pd.Series:
            if col not in df.columns:
                return pd.Series([0.0] * len(df))
            return pd.to_numeric(df[col], errors="coerce").fillna(0.0)

        load = num("Load Profile")
        pv_to_load = num("System to Load")
        batt_to_load = num("Battery to Load")
        grid_to_load = num("Grid to Load")
        pv_to_batt = num("System to Battery")
        grid_to_batt = num("Grid to Battery")
        system_to_grid = df["System to Grid"] if "System to Grid" in df.columns else None
        pv_to_grid = df["PV to Grid (kWh)"] if "PV to Grid (kWh)" in df.columns else None
        pv_ac = df["PV AC (kWh)"] if "PV AC (kWh)" in df.columns else None

        total_load_kwh = float(load.sum()) if len(load) else None
        pv_to_load_kwh = float(pv_to_load.sum())
        batt_to_load_kwh = float(batt_to_load.sum())
        grid_to_load_kwh = float(grid_to_load.sum())
        pv_to_batt_kwh = float(pv_to_batt.sum())
        grid_to_batt_kwh = float(grid_to_batt.sum())
        total_grid_purchases_kwh = grid_to_load_kwh + grid_to_batt_kwh

        pv_exports_kwh = None
        pv_exports_formula = None
        try:
            if pv_to_grid is not None:
                pv_exports_kwh = float(pd.to_numeric(pv_to_grid, errors="coerce").fillna(0.0).sum())
                pv_exports_formula = "sum('PV to Grid (kWh)')"
            elif system_to_grid is not None:
                pv_exports_kwh = float(pd.to_numeric(system_to_grid, errors="coerce").fillna(0.0).sum())
                pv_exports_formula = "sum('System to Grid')"
            elif pv_ac is not None:
                pv_exports_kwh = float(
                    pd.to_numeric(pv_ac, errors="coerce").fillna(0.0).sum()
                    - pv_to_load_kwh
                    - pv_to_batt_kwh
                )
                if pv_exports_kwh < 0 and abs(pv_exports_kwh) < 1e-6:
                    pv_exports_kwh = 0.0
                pv_exports_formula = "sum('PV AC (kWh)') - sum('System to Load') - sum('System to Battery')"
        except Exception:
            pv_exports_kwh = None
            pv_exports_formula = None

        if total_load_kwh and total_load_kwh > 0:
            self_sufficiency_pct = 100.0 * (1.0 - (grid_to_load_kwh / total_load_kwh))
        else:
            self_sufficiency_pct = None

        net = load - pv_to_load - batt_to_load
        peak_net_load_kw = float(net.max()) if len(net) else None

        battery_capacity_kwh = lookup_battery_capacity_kwh(
            base_input_dir, scenario, housing_type, county_slug
        )

        return {
            "battery_capacity_kwh": battery_capacity_kwh,
            "pv_to_load_kwh": pv_to_load_kwh,
            "batt_to_load_kwh": batt_to_load_kwh,
            "grid_to_load_kwh": grid_to_load_kwh,
            "pv_to_batt_kwh": pv_to_batt_kwh,
            "grid_to_batt_kwh": grid_to_batt_kwh,
            "pv_exports_kwh": pv_exports_kwh,
            "pv_exports_formula": pv_exports_formula,
            "total_grid_purchases_kwh": total_grid_purchases_kwh,
            "self_sufficiency_pct": self_sufficiency_pct,
            "peak_net_load_kw": peak_net_load_kw,
        }
    except Exception:
        return None


def latest_results_csv_path(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
    *,
    kind: str,
) -> Optional[str]:
    try:
        res_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug, "results", kind)
        if not os.path.isdir(res_dir):
            return None
        prefix = f"RESULTS_{kind}_annual_costs_{county_slug}_"
        return get_latest_csv_file(res_dir, prefix)
    except Exception:
        return None


def compute_energy_flow_metrics_without(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> Optional[dict]:
    """Compute no-PV/battery flows using Step 7 combined profiles."""
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    combined = os.path.join(county_dir, f"combined_profiles_{scenario}_{county_slug}.csv")
    if not os.path.exists(combined):
        return None
    try:
        df = pd.read_csv(combined)
        col = "electricity.real_and_simulated.for_typical_county_home.kwh"
        if col not in df.columns:
            return None
        load = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        total_load_kwh = float(load.sum())
        peak_net_load_kw = float(load.max())
        return {
            "battery_capacity_kwh": 0.0,
            "pv_to_load_kwh": 0.0,
            "batt_to_load_kwh": 0.0,
            "grid_to_load_kwh": total_load_kwh,
            "pv_to_batt_kwh": 0.0,
            "grid_to_batt_kwh": 0.0,
            "pv_exports_kwh": 0.0,
            "pv_exports_formula": "N/A (no PV)",
            "total_grid_purchases_kwh": total_load_kwh,
            "self_sufficiency_pct": 0.0,
            "peak_net_load_kw": peak_net_load_kw,
        }
    except Exception:
        return None


def parse_electricity_results(path: str, scenario: str) -> tuple[dict, dict]:
    """Return two dicts keyed by plan token -> dollars for (retail, nem3)."""
    retail: dict[str, float] = {}
    nem3: dict[str, float] = {}
    if not path or not os.path.exists(path):
        return retail, nem3
    try:
        df = pd.read_csv(path, index_col="scenario")
        row_name = f"{scenario}.solarstorage" if f"{scenario}.solarstorage" in df.index else scenario
        row = df.loc[row_name] if row_name in df.index else df.iloc[0]
        for c in row.index:
            s = str(c)
            if not s.startswith("electricity."):
                continue
            val = pd.to_numeric(row[c], errors="coerce")
            if pd.isna(val):
                continue
            is_nem3 = s.endswith("_NEM3")
            plan_token = s.split(".")[-1].replace("_NEM3", "")
            if is_nem3:
                nem3[plan_token] = float(val)
            else:
                retail[plan_token] = float(val)
        return retail, nem3
    except Exception:
        return retail, nem3


def parse_gas_results(path: str, scenario: str) -> dict:
    """Return dict plan -> dollars for scenario.solarstorage row."""
    out: dict[str, float] = {}
    if not path or not os.path.exists(path):
        return out
    try:
        df = pd.read_csv(path, index_col="scenario")
        row_name = f"{scenario}.solarstorage" if f"{scenario}.solarstorage" in df.index else scenario
        row = df.loc[row_name] if row_name in df.index else df.iloc[0]
        for c in row.index:
            s = str(c)
            if not s.startswith("gas."):
                continue
            val = pd.to_numeric(row[c], errors="coerce")
            if pd.isna(val):
                continue
            plan_token = s.split(".")[-1]
            out[plan_token] = float(val)
        return out
    except Exception:
        return out


def compute_cost_breakdowns(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> dict:
    """Return structured totals and per-plan electricity/gas annual costs."""
    e_path = latest_results_csv_path(base_input_dir, scenario, housing_type, county_slug, kind="electricity")
    g_path = latest_results_csv_path(base_input_dir, scenario, housing_type, county_slug, kind="gas")
    retail, nem3 = parse_electricity_results(e_path, scenario)
    gas = parse_gas_results(g_path, scenario)

    def best(d: dict) -> tuple[str, float] | tuple[None, None]:
        if not d:
            return (None, None)
        k = min(d, key=lambda k: d[k])
        return (k, float(d[k]))

    eb_retail = best(retail)
    eb_nem3 = best(nem3)
    gb = best(gas)

    return {
        "electricity": {"retail": retail, "nem3": nem3},
        "gas": gas,
        "totals": {
            "electricity_best_retail": eb_retail,
            "electricity_best_nem3": eb_nem3,
            "gas_best": gb,
        },
    }


def compute_assets_info(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> Optional[dict]:
    """Read PV and battery capacities for a county from electrified_assets.csv."""
    cap_csv = os.path.join(
        base_input_dir, scenario, housing_type, "CAPITAL_COSTS", "electrified_assets.csv"
    )
    if not os.path.exists(cap_csv):
        return None
    try:
        df = pd.read_csv(cap_csv)
        county_col = None
        for c in df.columns:
            if str(c).strip().lower() in ("county", "county_slug"):
                county_col = c
                break
        if county_col is not None:
            df_idx = df.set_index(county_col)
        else:
            df_idx = df

        def to_slug(x):
            try:
                return slugify_county_name(str(x))
            except Exception:
                return str(x)

        df_idx = df_idx.copy()
        if df_idx.index.name is None or any(isinstance(i, (int, float)) for i in df_idx.index):
            df_idx["__slug__"] = [to_slug(x) for x in range(len(df_idx))]
        match_row = None
        for _, r in df.iterrows():
            nm = r.get("County") or r.get(county_col) or ""
            if slugify_county_name(str(nm)) == county_slug:
                match_row = r
                break
        if match_row is None and not df.empty:
            match_row = df.iloc[0]
        out = {
            "Solar Capacity (kW)": None,
            "Battery Capacity (kWh)": None,
        }
        if match_row is not None:
            for key in out.keys():
                if key in match_row.index:
                    val = match_row[key]
                    if pd.isna(val):
                        out[key] = None
                    else:
                        out[key] = str(val)
        try:
            mtime = os.path.getmtime(cap_csv)
            out["CSV Path"] = cap_csv
            out["Last Modified"] = pd.Timestamp.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            out["CSV Path"] = cap_csv
            out["Last Modified"] = None
        return out
    except Exception:
        return None
