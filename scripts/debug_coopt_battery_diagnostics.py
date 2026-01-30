import argparse
import os
import sys

import pandas as pd

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _find_dispatch_csv(base_input_dir: str, scenario: str, housing_type: str, county: str) -> str:
    path = os.path.join(
        base_input_dir,
        scenario,
        housing_type,
        county,
        f"solar_storage_dispatch_profiles_{county}.csv",
    )
    if not os.path.exists(path):
        raise FileNotFoundError(f"Dispatch CSV not found: {path}")
    return path


def _find_price_series_csv(base_input_dir: str, scenario: str, housing_type: str, county: str) -> str | None:
    path = os.path.join(
        base_input_dir,
        scenario,
        housing_type,
        county,
        f"coopt_price_series_{county}.csv",
    )
    return path if os.path.exists(path) else None


def main() -> None:
    p = argparse.ArgumentParser(description="Debug co-opt battery sizing (PV surplus + price stats)")
    p.add_argument("--base-input-dir", default="data/loadprofiles")
    p.add_argument("--scenario", required=True)
    p.add_argument("--housing-type", default="single-family-detached")
    p.add_argument("--county", required=True, help="County slug (e.g., alameda)")
    p.add_argument("--out-dir", default=None, help="Optional output directory for plots")
    args = p.parse_args()

    csv_path = _find_dispatch_csv(args.base_input_dir, args.scenario, args.housing_type, args.county)
    df = pd.read_csv(csv_path)

    required = ["PV AC (kWh)", "System to Load", "System to Battery", "Load Profile", "Grid to Load"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns in {csv_path}: {missing}")

    pv = pd.to_numeric(df["PV AC (kWh)"], errors="coerce").fillna(0.0)
    pv_to_load = pd.to_numeric(df["System to Load"], errors="coerce").fillna(0.0)
    pv_to_batt = pd.to_numeric(df["System to Battery"], errors="coerce").fillna(0.0)
    load = pd.to_numeric(df["Load Profile"], errors="coerce").fillna(0.0)
    grid_to_load = pd.to_numeric(df["Grid to Load"], errors="coerce").fillna(0.0)

    if "PV to Grid (kWh)" in df.columns:
        pv_to_grid = pd.to_numeric(df["PV to Grid (kWh)"], errors="coerce").fillna(0.0)
    elif "System to Grid" in df.columns:
        pv_to_grid = pd.to_numeric(df["System to Grid"], errors="coerce").fillna(0.0)
    else:
        pv_to_grid = pd.Series([0.0] * len(df))

    pv_surplus = (pv - pv_to_load - pv_to_batt - pv_to_grid).clip(lower=0.0)
    pv_used_onsite = pv_to_load + pv_to_batt

    print("=== Co-opt PV/Battery Diagnostics ===")
    print(f"Dispatch CSV: {csv_path}")
    print(f"Annual Load (kWh): {load.sum():,.1f}")
    print(f"Annual PV AC (kWh): {pv.sum():,.1f}")
    print(f"Annual PV to Load (kWh): {pv_to_load.sum():,.1f}")
    print(f"Annual PV to Battery (kWh): {pv_to_batt.sum():,.1f}")
    print(f"Annual PV to Grid (kWh): {pv_to_grid.sum():,.1f}")
    print(f"Hours with PV to Grid > 0: {(pv_to_grid > 1e-6).sum()}")
    print(f"Max PV to Grid hour (kWh): {pv_to_grid.max():.3f}")
    print(f"Annual PV surplus (kWh): {pv_surplus.sum():,.1f}")
    print(f"Annual PV used onsite (kWh): {pv_used_onsite.sum():,.1f}")
    print(f"Annual Grid to Load (kWh): {grid_to_load.sum():,.1f}")

    # Storage value diagnostic (upper bound within 24 hours, PV-only charging)
    price_csv = _find_price_series_csv(args.base_input_dir, args.scenario, args.housing_type, args.county)
    if price_csv:
        prices = pd.read_csv(price_csv)
        if "import_price_usd_per_kwh" in prices.columns and "export_price_usd_per_kwh" in prices.columns:
            import_prices = pd.to_numeric(prices["import_price_usd_per_kwh"], errors="coerce").fillna(0.0).tolist()
            export_prices = pd.to_numeric(prices["export_price_usd_per_kwh"], errors="coerce").fillna(0.0).tolist()
            n = min(len(import_prices), len(export_prices), len(pv_to_grid))
            import_prices = import_prices[:n]
            export_prices = export_prices[:n]
            exports_kwh = pv_to_grid.iloc[:n].astype(float).tolist()

            rte = 0.96
            window = 24
            total_value = 0.0
            total_exports = 0.0
            for i in range(n):
                export_kwh = float(exports_kwh[i])
                if export_kwh <= 0:
                    continue
                future = import_prices[i + 1 : i + 1 + window]
                if not future:
                    continue
                max_future = max(future)
                delta = max_future - float(export_prices[i])
                if delta > 0:
                    total_value += export_kwh * delta * rte
                total_exports += export_kwh

            avg_value_per_kwh = (total_value / total_exports) if total_exports > 0 else 0.0
            print(f"Storage value (24h upper bound, PV-only): ${total_value:,.2f}/yr")
            print(f"Avg value per exported kWh: ${avg_value_per_kwh:.3f}")

            summary_path = os.path.join(out_dir, f"coopt_storage_value_{args.county}.csv")
            pd.DataFrame(
                [
                    {
                        "storage_value_24h_upper_bound_usd_per_year": total_value,
                        "exported_kwh": total_exports,
                        "avg_value_per_export_kwh_usd": avg_value_per_kwh,
                        "window_hours": window,
                        "round_trip_efficiency": rte,
                    }
                ]
            ).to_csv(summary_path, index=False)
            print(f"Wrote storage value summary: {summary_path}")
        else:
            print(f"Price series missing required columns: {price_csv}")
    else:
        print("Price series not found (run Step9b with --debug-prices to generate).")

    out_dir = args.out_dir or os.path.dirname(csv_path)
    os.makedirs(out_dir, exist_ok=True)

    try:
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(3, 1, figsize=(10, 8), tight_layout=True)

        # Weekly overlay (first 168 hours)
        n = min(168, len(df))
        axes[0].plot(load.iloc[:n].values, label="Load", color="#444")
        axes[0].plot(pv.iloc[:n].values, label="PV AC", color="#1f77b4")
        axes[0].plot(pv_to_grid.iloc[:n].values, label="PV to Grid", color="#ff7f0e")
        axes[0].set_title("First Week: Load vs PV vs PV Export")
        axes[0].set_ylabel("kWh")
        axes[0].legend()

        # Distribution of PV surplus / export
        axes[1].hist(pv_surplus, bins=40, color="#2ca02c", alpha=0.8)
        axes[1].set_title("PV Surplus Distribution")
        axes[1].set_xlabel("kWh")
        axes[1].set_ylabel("Hours")

        # Daily totals
        daily = df.copy()
        daily["day"] = (pd.RangeIndex(len(df)) // 24).astype(int)
        daily_pv = daily.groupby("day")["PV AC (kWh)"].sum()
        daily_export = daily.groupby("day")[pv_to_grid.name].sum() if pv_to_grid.name in daily.columns else pv_to_grid.groupby(daily["day"]).sum()
        axes[2].plot(daily_pv.values, label="Daily PV AC", color="#1f77b4")
        axes[2].plot(daily_export.values, label="Daily PV to Grid", color="#ff7f0e")
        axes[2].set_title("Daily PV vs Export")
        axes[2].set_xlabel("Day of Year")
        axes[2].set_ylabel("kWh")
        axes[2].legend()

        fig_path = os.path.join(out_dir, f"coopt_battery_debug_{args.county}.png")
        fig.savefig(fig_path, dpi=150)
        plt.close(fig)
        print(f"Wrote plot: {fig_path}")
    except Exception as e:
        print(f"Plotting failed: {e}")


if __name__ == "__main__":
    main()
