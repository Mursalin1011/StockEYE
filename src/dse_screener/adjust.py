"""Back-adjust stored prices for corporate actions. Raw data is never modified."""

from __future__ import annotations

import pandas as pd

PRICE_FIELDS = ["open", "high", "low", "close", "ltp"]


def apply_adjustments(
    prices: pd.DataFrame, actions: pd.DataFrame, include_cash: bool = True
) -> pd.DataFrame:
    """Return an adjusted copy with `price_adj` and `volume_adj` columns.

    Rows before each ex-date get prices x factor and volume x (1 + bonus).
    `include_cash=False` adjusts for bonus shares only.
    """
    out = prices.copy()
    out["date"] = pd.to_datetime(out["date"])
    out["price_adj"] = 1.0
    out["volume_adj"] = 1.0
    if not actions.empty:
        acts = actions.dropna(subset=["ex_date"])
        rows_by_code = out.groupby("code", sort=False).indices    # row positions per stock, computed once
        date_col = out.columns.get_loc("date")
        p_col, v_col = out.columns.get_loc("price_adj"), out.columns.get_loc("volume_adj")
        for ev in acts.itertuples(index=False):
            idx = rows_by_code.get(ev.code)
            if idx is None:
                continue
            before = idx[out.iloc[idx, date_col].to_numpy() < pd.Timestamp(ev.ex_date).to_datetime64()]
            out.iloc[before, p_col] *= ev.price_factor if include_cash else ev.bonus_factor
            out.iloc[before, v_col] *= ev.volume_factor

    for col in PRICE_FIELDS:
        out[col] = out[col] * out["price_adj"]
    out["volume"] = (out["volume"].astype("float") * out["volume_adj"]).round().astype("Int64")
    # YCP is the previous (now adjusted) close; first row per code keeps DSE's value scaled.
    out = out.sort_values(["code", "date"])
    out["ycp"] = out.groupby("code")["close"].shift().fillna(out["ycp"] * out["price_adj"])
    return out.reset_index(drop=True)
