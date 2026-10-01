"""Plotly figures for the dashboard. Pure functions: data in, figure out.

Colors follow the validated reference palette (dataviz skill): strategies use the
categorical slots in a fixed order so a strategy keeps its color everywhere;
price is neutral ink; light and dark steps are chosen separately.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

PALETTE = {
    "light": {
        "surface": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781",
        "grid": "#e1e0d9", "axis": "#c3c2b7", "volume": "#86b6ef",
        "series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"],
    },
    "dark": {
        "surface": "#1a1a19", "ink": "#ffffff", "ink2": "#c3c2b7", "muted": "#898781",
        "grid": "#2c2c2a", "axis": "#383835", "volume": "#184f95",
        "series": ["#3987e5", "#d95926", "#199e70", "#c98500"],
    },
}

# Fixed slot per strategy: color follows the strategy, never its rank or presence
STRATEGY_SLOT = {"quiet_accumulation": 0, "base_breakout": 1, "big_hands": 2}
STRATEGY_SYMBOL = {"quiet_accumulation": "circle", "base_breakout": "triangle-up", "big_hands": "diamond"}


def strategy_color(name: str, mode: str = "light") -> str:
    return PALETTE[mode]["series"][STRATEGY_SLOT.get(name, 3)]


def price_volume_chart(
    prices: pd.DataFrame,
    signals: dict[str, pd.Series] | None = None,
    titles: dict[str, str] | None = None,
    ex_dates: list[pd.Timestamp] | None = None,
    avg_volume_days: int = 20,
    mode: str = "light",
    height: int = 520,
) -> go.Figure:
    """Adjusted close (top) and volume (bottom) on a shared date axis.

    Two panels instead of a dual axis: price and volume have different scales.
    signals: strategy name -> boolean Series aligned to prices (first day of each run is marked).
    """
    c = PALETTE[mode]
    p = prices.sort_values("date")   # keep the index: signal Series are aligned to it
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.68, 0.32], vertical_spacing=0.04)

    fig.add_trace(go.Scatter(
        x=p["date"], y=p["close"], name="Close (adjusted)", mode="lines",
        line=dict(color=c["ink2"], width=2), hovertemplate="%{x|%d %b %Y}<br>Close %{y:,.1f}<extra></extra>",
    ), row=1, col=1)

    for name, sig in (signals or {}).items():
        sig = sig.reindex(p.index, fill_value=False).astype(bool)
        starts = sig & ~sig.shift(1, fill_value=False)
        if not starts.any():
            continue
        pts = p[starts]
        fig.add_trace(go.Scatter(
            x=pts["date"], y=pts["close"], mode="markers", name=(titles or {}).get(name, name),
            marker=dict(color=strategy_color(name, mode), size=10, symbol=STRATEGY_SYMBOL.get(name, "circle"),
                        line=dict(color=c["surface"], width=2)),
            hovertemplate="%{x|%d %b %Y}<br>" + (titles or {}).get(name, name) + "<extra></extra>",
        ), row=1, col=1)

    fig.add_trace(go.Bar(
        x=p["date"], y=p["volume"], name="Volume", marker=dict(color=c["volume"], line=dict(width=0)),
        hovertemplate="%{x|%d %b %Y}<br>Volume %{y:,.0f}<extra></extra>",
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=p["date"], y=p["volume"].astype(float).rolling(avg_volume_days).mean(),
        name=f"{avg_volume_days}-day avg volume", mode="lines", line=dict(color=c["ink2"], width=2),
        hovertemplate="%{x|%d %b %Y}<br>Avg %{y:,.0f}<extra></extra>",
    ), row=2, col=1)

    for d in ex_dates or []:
        fig.add_vline(x=d, line=dict(color=c["muted"], width=1, dash="dot"), row="all", col=1)

    axis = dict(gridcolor=c["grid"], linecolor=c["axis"], tickfont=dict(color=c["muted"]), zeroline=False)
    fig.update_xaxes(**axis, showspikes=True, spikemode="across", spikecolor=c["muted"], spikethickness=1)
    fig.update_yaxes(**axis)
    fig.update_yaxes(title_text="Price (BDT)", title_font=dict(color=c["ink2"]), row=1, col=1)
    fig.update_yaxes(title_text="Volume", title_font=dict(color=c["ink2"]), row=2, col=1)
    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=8, b=8), hovermode="x unified", bargap=0.15,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family='system-ui, -apple-system, "Segoe UI", sans-serif', color=c["ink"]),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0, font=dict(color=c["ink2"])),
    )
    return fig
