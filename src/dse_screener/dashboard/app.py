"""DSE Screener dashboard. Run with: python -m dse_screener dashboard"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dse_screener import engine, quality, rules
from dse_screener.config import CONFIG_DIR, list_profiles, load_profile, load_settings, load_universe
from dse_screener.dashboard.charts import price_volume_chart
from dse_screener.db import Database
from dse_screener.report import DISCLAIMER
from dse_screener.strategies import REGISTRY

st.set_page_config(page_title="DSE Screener", page_icon="ðŸ“Š", layout="wide")


# --- data access (cached) ----------------------------------------------------

@st.cache_resource
def get_settings():
    return load_settings()


def get_db() -> Database:
    s = get_settings()
    return Database(s.resolve(s.paths.db), check_same_thread=False)


@st.cache_data(ttl=300)
def adjusted_prices(codes: tuple[str, ...]) -> pd.DataFrame:
    return engine.load_adjusted_prices(get_db(), get_settings(), list(codes))


@st.cache_data(ttl=300)
def quality_metrics(codes: tuple[str, ...]) -> pd.DataFrame:
    return quality.compute_quality_metrics(get_db(), list(codes))


@st.cache_data(ttl=300)
def runs() -> pd.DataFrame:
    return get_db().load_runs()


@st.cache_data(ttl=300)
def run_details(run_ids: tuple[int, ...]) -> tuple[pd.DataFrame, pd.DataFrame]:
    db = get_db()
    return db.load_run_picks(list(run_ids)), db.load_run_signals(list(run_ids))


@st.cache_data(ttl=300)
def table(name: str, codes: tuple[str, ...]) -> pd.DataFrame:
    db = get_db()
    if name == "news":
        return db.load_news(list(codes))
    if name == "companies":
        return db.load_companies(list(codes))
    if name == "corporate_actions":
        return db.load_corporate_actions(list(codes))
    return db.load_table(name, list(codes))


@st.cache_data(ttl=300)
def strategy_signals(profile_name: str, code: str, codes: tuple[str, ...]) -> dict[str, pd.Series]:
    """Every date each of the profile's strategies fired for this stock."""
    prices = adjusted_prices(codes)
    g = prices[prices["code"] == code].reset_index(drop=True)
    out = {}
    for strat, _cfg in engine.build_strategies(load_profile(profile_name)):
        if len(g) >= strat.min_history:
            res = strat.compute(g)
            out[strat.name] = res["signal"] & (res.index >= strat.min_history) & (g["volume"] > 0)
    return out


def theme_mode() -> str:
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except AttributeError:
        return "light"


TITLES = {name: cls.title for name, cls in REGISTRY.items()}


def stock_chart(code: str, profile_name: str, codes: tuple[str, ...], days: int | None = 250, key: str = ""):
    prices = adjusted_prices(codes)
    g = prices[prices["code"] == code].reset_index(drop=True)
    sig = strategy_signals(profile_name, code, codes)
    if days:
        start = len(g) - days
        g = g.iloc[max(start, 0):]
        sig = {k: v.iloc[max(start, 0):] for k, v in sig.items()}
    acts = table("corporate_actions", codes)
    ex = [d for d in acts.loc[acts["code"] == code, "ex_date"].dropna() if d >= g["date"].min()]
    fig = price_volume_chart(g, sig, TITLES, ex, mode=theme_mode())
    st.plotly_chart(fig, width="stretch", key=f"chart-{key}-{code}")
    st.caption("Markers: first day of each signal for this profile's strategies. "
               "Dotted lines: dividend/bonus ex-dates. Prices adjusted for dividends and bonus shares.")


# --- layout ------------------------------------------------------------------

settings = get_settings()
profile_names = list_profiles(settings)
profiles = {n: load_profile(n) for n in profile_names}
universe_codes = tuple(sorted({c for p in profiles.values() for c in load_universe(p.universe).codes}))

all_runs = runs()
with st.sidebar:
    st.title("ðŸ“Š DSE Screener")
    first, last = get_db().date_range()
    st.caption(f"Prices stored: {first} â†’ {last}")
    dates = sorted(all_runs["as_of"].unique(), reverse=True) if not all_runs.empty else []
    as_of = st.selectbox("Screen date", dates, format_func=lambda d: pd.Timestamp(d).strftime("%a %d %b %Y")) \
        if dates else None
    if st.button("Run screen now", help="Screens all profiles on the latest stored day and saves the result"):
        db = get_db()
        for p in profiles.values():
            db.save_screen(engine.run_profile(db, settings, p), p.model_dump_json(by_alias=True))
        st.cache_data.clear()
        st.rerun()
    st.divider()
    st.caption(DISCLAIMER)

tab_picks, tab_explore, tab_history, tab_quality, tab_settings = st.tabs(
    ["Picks", "Stock explorer", "History", "Quality", "Settings"]
)

# Picks ----------------------------------------------------------------------
with tab_picks:
    if as_of is None:
        st.info("No saved screens yet. Use **Run screen now** in the sidebar, or wait for the daily job.")
    else:
        day_runs = all_runs[all_runs["as_of"] == as_of].set_index("profile")
        picks, signals = run_details(tuple(int(r) for r in day_runs["run_id"]))
        for name in profile_names:
            if name not in day_runs.index:
                continue
            run = day_runs.loc[name]
            prof = profiles[name]
            p_picks = picks[picks["run_id"] == run["run_id"]]
            p_sigs = signals[signals["run_id"] == run["run_id"]]
            st.subheader(f"{name.title()}")
            st.caption(prof.description)
            c1, c2, c3 = st.columns(3)
            c1.metric("Pass quality", f"{run['passed_quality']}/{run['universe_size']}")
            c2.metric("Strategy signals", len(p_sigs))
            c3.metric("Shortlist", len(p_picks))
            if p_picks.empty:
                st.info("No stock meets the bar on this date.")
            news = table("news", universe_codes)
            for pk in p_picks.itertuples():
                strategies = ", ".join(TITLES.get(s, s) for s in pk.strategies)
                with st.expander(f"**{pk.rank}. {pk.code}** Â· score {pk.final_score:.0f} Â· {strategies}",
                                 expanded=pk.rank == 1):
                    left, right = st.columns([2, 3])
                    with left:
                        for reason in pk.reasons:
                            head, sep, body = reason.partition("): ")
                            if sep:
                                st.markdown(f"**{head})**")
                                st.markdown("\n".join(f"- {b}" for b in body.split("; ")))
                            else:
                                st.markdown(f"- {reason}")
                        recent = news[(news["code"] == pk.code)
                                      & (news["post_date"] <= pd.Timestamp(as_of))
                                      & (news["post_date"] >= pd.Timestamp(as_of) - pd.Timedelta(days=30))
                                      & ~news["body"].str.startswith("(Cont")]
                        if not recent.empty:
                            st.markdown("**Recent news**")
                            for n in recent.sort_values("post_date", ascending=False).head(5).itertuples():
                                st.markdown(f"- {n.post_date:%d %b}: {n.title.split(': ', 1)[-1]}",
                                            help=n.body)
                    with right:
                        stock_chart(pk.code, name, universe_codes, key=f"pick-{name}")
            st.divider()

# Stock explorer -------------------------------------------------------------
with tab_explore:
    c1, c2, c3 = st.columns([2, 2, 2])
    code = c1.selectbox("Stock", universe_codes, index=universe_codes.index("GP") if "GP" in universe_codes else 0)
    prof_name = c2.radio("Strategies from profile", profile_names, horizontal=True)
    span = c3.radio("Range", ["6M", "1Y", "All"], index=1, horizontal=True)
    days = {"6M": 125, "1Y": 250, "All": None}[span]
    stock_chart(code, prof_name, universe_codes, days=days, key="explore")

    comp = table("companies", universe_codes).set_index("code")
    m = quality_metrics(universe_codes)
    if code in comp.index:
        info = comp.loc[code]
        st.markdown(f"**{info['name']}** Â· {info['sector']} Â· Category {info['category']}")
        k = st.columns(6)
        k[0].metric("Market cap", f"à§³{(info['market_cap_mn'] or 0) / 1000:,.1f} bn")
        k[1].metric("P/E (trailing)", f"{m.loc[code, 'pe']:.1f}" if pd.notna(m.loc[code, "pe"]) else "â€“")
        k[2].metric("Dividend streak", f"{m.loc[code, 'dividend_streak']} yrs")
        k[3].metric("Dividend yield", f"{m.loc[code, 'dividend_yield']:.1f}%"
                    if pd.notna(m.loc[code, "dividend_yield"]) else "â€“")
        k[4].metric("Sponsor + govt", f"{m.loc[code, 'strategic_pct']:.1f}%")
        chg = m.loc[code, "institute_change_pp"]
        k[5].metric("Institutions", f"{chg:+.1f} pts" if pd.notna(chg) else "â€“", help="Change across stored snapshots")

    left, right = st.columns(2)
    with left:
        st.markdown("**Shareholding (%)**")
        sh = table("shareholding", universe_codes)
        st.dataframe(sh[sh["code"] == code].drop(columns="code").sort_values("as_of", ascending=False),
                     hide_index=True, width="stretch")
        st.markdown("**Dividends & bonus (ex-dates)**")
        acts = table("corporate_actions", universe_codes)
        st.dataframe(
            acts.loc[acts["code"] == code, ["record_date", "ex_date", "cash_pct", "stock_pct", "revised"]]
            .sort_values("record_date", ascending=False),
            hide_index=True, width="stretch",
            column_config={"ex_date": st.column_config.DateColumn("ex_date"),
                           "revised": st.column_config.CheckboxColumn("AGM revised")},
        )
        st.markdown("**Annual results**")
        an = table("annual_financials", universe_codes)
        st.dataframe(an[an["code"] == code].drop(columns="code").sort_values("year", ascending=False),
                     hide_index=True, width="stretch")
    with right:
        st.markdown("**News**")
        news = table("news", universe_codes)
        n = news[(news["code"] == code) & ~news["body"].str.startswith("(Cont")]
        st.dataframe(
            n.sort_values("post_date", ascending=False)[["post_date", "title", "body"]],
            hide_index=True, width="stretch", height=560,
            column_config={"post_date": st.column_config.DateColumn("date"),
                           "body": st.column_config.TextColumn("news", width="large")},
        )

# History --------------------------------------------------------------------
with tab_history:
    if all_runs.empty:
        st.info("No saved screens yet.")
    else:
        picks, _ = run_details(tuple(int(r) for r in all_runs["run_id"]))
        merged = picks.merge(all_runs[["run_id", "as_of", "profile"]], on="run_id")
        merged["pick"] = merged["code"] + " (" + merged["final_score"].round().astype(int).astype(str) + ")"
        hist = (merged.groupby(["as_of", "profile"])["pick"].agg(", ".join).unstack("profile")
                .reindex(columns=[p for p in profile_names if p in merged["profile"].unique()]))
        st.dataframe(hist.sort_index(ascending=False), width="stretch")
        st.caption("Latest saved run per day and profile. The backtest (M6) will add what happened next.")

# Quality --------------------------------------------------------------------
with tab_quality:
    m = quality_metrics(universe_codes)
    prof_name = st.radio("Profile", profile_names, horizontal=True, key="q-profile")
    qf = profiles[prof_name].filters.get("quality")
    res = rules.evaluate(m, qf.rules if qf and qf.enabled else {})
    shown = m.join(res)
    shown["failures"] = shown["failures"].map(lambda f: "; ".join(f))
    st.dataframe(
        shown.sort_values(["passed", "market_cap_mn"], ascending=[False, False]),
        width="stretch",
        column_config={"passed": st.column_config.CheckboxColumn("pass"),
                       "market_cap_mn": st.column_config.NumberColumn("mcap (mn)", format="%,.0f")},
    )
    st.caption(f"{int(res['passed'].sum())}/{len(res)} pass. Rules: config/profiles/{prof_name}.yaml")

# Settings -------------------------------------------------------------------
with tab_settings:
    st.caption("Read-only view. Edit these files, then refresh. Secrets (config/secrets.yaml) are never shown.")
    files = [CONFIG_DIR / "settings.yaml"] + [CONFIG_DIR / "profiles" / f"{n}.yaml" for n in profile_names]
    for path in files:
        with st.expander(str(path.relative_to(CONFIG_DIR.parent)), expanded=False):
            st.code(path.read_text(encoding="utf-8"), language="yaml")
