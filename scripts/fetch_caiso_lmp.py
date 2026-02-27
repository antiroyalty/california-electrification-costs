"""
Fetch hourly Day-Ahead Market LMP from CAISO OASIS for Alameda and Fresno counties.

Both counties are in PG&E territory. This script fetches:
  - PGAE_APND: PG&E aggregate pricing node (territory-wide average, reliable baseline)
  - NP15_7_B3: Northern CA / Bay Area hub (proxy for Alameda)
  - SP26_7_B3: San Joaquin Valley area (proxy for Fresno) -- verify node name below

NOTE ON NODES:
  CAISO has hundreds of pricing nodes. The aggregate node (PGAE_APND) is the safest
  starting point. To find nodes physically closest to Alameda or Fresno, query the
  node list via CAISO OASIS:
    http://oasis.caiso.com/oasisapi/GroupZip?groupid=CAISO_PRICING_NODE&version=1
  Or use Paul's node list if he's already pulled it.

Usage:
    python3 scripts/fetch_caiso_lmp.py
    python3 scripts/fetch_caiso_lmp.py --year 2022 --market RTM

Output:
    data/caiso_lmp/caiso_lmp_<year>_<market>.csv   -- hourly LMP, all nodes
    data/caiso_lmp/caiso_lmp_<year>_<market>_summary.csv -- daily/monthly stats
"""

import os
import io
import time
import zipfile
import argparse
import requests
import pandas as pd
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OASIS_URL = "https://oasis.caiso.com/oasisapi/SingleZip"

# Nodes to fetch. Keys are human-readable labels, values are CAISO node IDs.
# Verify NP15/SP26 names against the CAISO node list before citing in a paper.
NODES = {
    "pge_aggregate": "PGAE_APND",   # PG&E territory aggregate — most reliable
    "alameda_np15":  "NP15_7_B3",   # Northern CA / Bay Area hub — proxy for Alameda
    "fresno_sp26":   "SP26_7_B3",   # San Joaquin hub — proxy for Fresno (verify this)
}

OUTPUT_DIR = "data/caiso_lmp"

# ---------------------------------------------------------------------------
# CAISO OASIS API fetch
# ---------------------------------------------------------------------------

def fetch_lmp_month(node_id: str, year: int, month: int, market: str) -> pd.DataFrame:
    """Fetch one month of hourly LMP for a single node. Returns a DataFrame."""
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)

    # Build URL manually — requests.get(params=...) URL-encodes colons as %3A,
    # which CAISO's API rejects. Datetime colons must be passed literally.
    start_str = start.strftime("%Y%m%dT%H:%M-0000")
    end_str   = end.strftime("%Y%m%dT%H:%M-0000")
    url = (
        f"{OASIS_URL}?queryname=PRC_LMP"
        f"&market_run_id={market}"
        f"&node={node_id}"
        f"&startdatetime={start_str}"
        f"&enddatetime={end_str}"
        f"&version=12"
        f"&resultformat=6"
    )

    response = requests.get(url, timeout=60)
    response.raise_for_status()

    # Response is a ZIP containing one or more CSVs
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        csv_names = [n for n in zf.namelist() if n.endswith(".csv")]
        if not csv_names:
            raise ValueError(f"No CSV in ZIP for node={node_id}, {year}-{month:02d}")
        with zf.open(csv_names[0]) as f:
            df = pd.read_csv(f)

    return df


def fetch_lmp_year(node_id: str, node_label: str, year: int, market: str) -> pd.DataFrame:
    """Fetch a full year of LMP for one node, month by month."""
    frames = []
    for month in range(1, 13):
        print(f"  Fetching {node_label} ({node_id}) {year}-{month:02d}...", end=" ")
        try:
            df = fetch_lmp_month(node_id, year, month, market)
            frames.append(df)
            print(f"OK ({len(df)} rows)")
        except Exception as e:
            print(f"FAILED: {e}")
        time.sleep(1)  # be polite to the API

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# Parsing and cleaning
# ---------------------------------------------------------------------------

def parse_lmp_response(df_raw: pd.DataFrame, node_label: str) -> pd.DataFrame:
    """
    Extract hourly LMP values from the raw CAISO OASIS response.
    CAISO returns columns including INTERVALSTARTTIME_GMT, MW (the LMP value),
    and LMP_TYPE (which breaks LMP into energy, congestion, loss components).
    We want LMP_TYPE == 'LMP' (total).
    """
    # Column names vary slightly across CAISO query types — normalize to uppercase
    df = df_raw.copy()
    df.columns = [c.strip().upper() for c in df.columns]

    # Keep only the total LMP row (not congestion/loss components)
    if "LMP_TYPE" in df.columns:
        df = df[df["LMP_TYPE"] == "LMP"].copy()

    # Parse timestamp
    time_col = next((c for c in df.columns if "STARTTIME" in c or "INTERVALSTART" in c), None)
    if time_col is None:
        raise ValueError(f"No timestamp column found. Columns: {df.columns.tolist()}")

    df["timestamp"] = pd.to_datetime(df[time_col], utc=True).dt.tz_convert("America/Los_Angeles")
    df["timestamp"] = df["timestamp"].dt.tz_localize(None)  # drop tz for easier CSV handling

    # Rename the price column
    price_col = next((c for c in df.columns if c in ("MW", "VALUE", "LMP")), None)
    if price_col is None:
        raise ValueError(f"No price column found. Columns: {df.columns.tolist()}")

    df["lmp_usd_per_mwh"] = pd.to_numeric(df[price_col], errors="coerce")
    df["node"] = node_label

    return df[["timestamp", "node", "lmp_usd_per_mwh"]].dropna()


# ---------------------------------------------------------------------------
# Summary statistics
# ---------------------------------------------------------------------------

def build_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Build monthly and annual summary stats per node."""
    df = df.copy()
    df["month"] = df["timestamp"].dt.to_period("M")

    monthly = (
        df.groupby(["node", "month"])["lmp_usd_per_mwh"]
        .agg(mean="mean", median="median", p10=lambda x: x.quantile(0.10),
             p90=lambda x: x.quantile(0.90), min="min", max="max", count="count")
        .reset_index()
    )

    # Flag the highest and lowest 24-hr average days per node
    df["date"] = df["timestamp"].dt.date
    daily_avg = df.groupby(["node", "date"])["lmp_usd_per_mwh"].mean().reset_index()
    daily_avg.columns = ["node", "date", "daily_avg_lmp"]

    for node in df["node"].unique():
        node_daily = daily_avg[daily_avg["node"] == node].sort_values("daily_avg_lmp")
        print(f"\n  {node} — top/bottom LMP days:")
        print(f"    Lowest:  {node_daily.iloc[0]['date']}  avg ${node_daily.iloc[0]['daily_avg_lmp']:.2f}/MWh")
        print(f"    Highest: {node_daily.iloc[-1]['date']} avg ${node_daily.iloc[-1]['daily_avg_lmp']:.2f}/MWh")

    return monthly


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Fetch CAISO DAM LMP for Alameda and Fresno nodes")
    parser.add_argument("--year",   type=int, default=2023, help="Calendar year to fetch (default: 2023)")
    parser.add_argument("--market", type=str, default="DAM",
                        choices=["DAM", "RTM", "HASP"],
                        help="CAISO market type (default: DAM)")
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path     = os.path.join(OUTPUT_DIR, f"caiso_lmp_{args.year}_{args.market}.csv")
    summary_path = os.path.join(OUTPUT_DIR, f"caiso_lmp_{args.year}_{args.market}_summary.csv")

    all_frames = []

    for label, node_id in NODES.items():
        print(f"\nFetching {label} ({node_id}) for {args.year} [{args.market}]...")
        df_raw = fetch_lmp_year(node_id, label, args.year, args.market)
        if df_raw.empty:
            print(f"  WARNING: no data returned for {label}")
            continue
        df_parsed = parse_lmp_response(df_raw, label)
        all_frames.append(df_parsed)
        print(f"  {len(df_parsed)} hourly records parsed.")

    if not all_frames:
        print("No data fetched. Check node names and API connectivity.")
        return

    combined = pd.concat(all_frames, ignore_index=True).sort_values(["node", "timestamp"])
    combined.to_csv(out_path, index=False)
    print(f"\nSaved hourly LMP → {out_path}")

    print("\nBuilding summary statistics...")
    summary = build_summary(combined)
    summary.to_csv(summary_path, index=False)
    print(f"Saved summary → {summary_path}")

    # Quick sanity check
    print("\n--- Annual averages by node ---")
    print(combined.groupby("node")["lmp_usd_per_mwh"].mean().round(2).to_string())


if __name__ == "__main__":
    main()
