"""Resolve a universe name to trading codes (fixed list or query over stored company pages)."""

from __future__ import annotations

from .config import load_universe
from .db import Database


def universe_codes(name: str, db: Database) -> list[str]:
    u = load_universe(name)
    if u.query is None:
        return list(u.codes)
    q = u.query
    comp = db.load_companies()
    sel = comp[comp["instrument_type"].isin(q.instrument_types)]
    if q.active_only:
        sel = sel[sel["operational_status"].fillna("Active").str.lower() == "active"]
    return sorted(set(sel["code"]) - set(q.exclude))
