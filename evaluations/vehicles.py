from __future__ import annotations

import pandas as pd


def vehicle_annual_adders_from_ledger(ledger_df: pd.DataFrame) -> pd.DataFrame:
    """Return county-indexed EV/ICE annual O&M adders from a capital ledger DataFrame.

    Output columns:
      - ev_operating: annual O&M for electric vehicle rows (appliance_category='electric', appliance_type='vehicle_charging')
      - ice_operating: annual O&M for ICE vehicle rows (appliance_category='gas', appliance_type='vehicle_fuel')
    Missing columns are filled with sensible defaults; returns an index of 'county_slug'.
    """
    df = ledger_df.copy() if ledger_df is not None else pd.DataFrame()
    if df.empty:
        return pd.DataFrame(columns=["ev_operating", "ice_operating"]).set_index(pd.Index([], name="county_slug"))

    # Ensure required columns exist
    for col in ["county_slug", "appliance_category", "appliance_type", "annual_operating_cost"]:
        if col not in df.columns:
            df[col] = 0.0 if col != "appliance_type" and col != "county_slug" else ""

    ev = (
        df[(df["appliance_category"] == "electric") & (df["appliance_type"] == "vehicle_charging")]
        .groupby("county_slug", as_index=False)["annual_operating_cost"].sum()
        .rename(columns={"annual_operating_cost": "ev_operating"})
    )
    ice = (
        df[(df["appliance_category"] == "gas") & (df["appliance_type"] == "vehicle_fuel")]
        .groupby("county_slug", as_index=False)["annual_operating_cost"].sum()
        .rename(columns={"annual_operating_cost": "ice_operating"})
    )

    out = pd.DataFrame({"county_slug": pd.unique(df["county_slug"])})
    out = (
        out.merge(ev, on="county_slug", how="left")
        .merge(ice, on="county_slug", how="left")
        .fillna({"ev_operating": 0.0, "ice_operating": 0.0})
    )
    return out.set_index("county_slug")

