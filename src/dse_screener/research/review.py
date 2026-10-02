"""AI review: research PDFs + StockEYE data -> Claude (guided by ANALYST.md) -> structured views and calls.

One request per review. The analyst guide and the DSE code directory form a stable, cached system
prompt; the PDFs go in as document blocks (Claude reads tables and charts, not just extracted text);
StockEYE's data goes in as JSON. The answer is constrained to a JSON schema and validated.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, field_validator

from ..config import Settings
from ..db import Database
from . import context as ctx
from . import documents, ledger

log = logging.getLogger(__name__)

Stance = Literal["bullish", "bearish", "neutral"]
HORIZONS = (5, 20, 60)


# --- output shape -------------------------------------------------------------------------------

class _Confidence(BaseModel):
    """Confidence is a probability in %: clip to 0-100."""

    @field_validator("confidence", check_fields=False)
    @classmethod
    def _clip(cls, v) -> float:
        return float(min(max(float(v), 0), 100))


class MarketView(_Confidence):
    stance: Stance
    confidence: float
    horizon_days: int
    summary: str
    drivers: list[str]
    risks: list[str]


class MacroItem(BaseModel):
    topic: str
    summary: str
    impact: Literal["positive", "negative", "mixed", "neutral"]
    sectors: list[str]
    source: str


class SectorView(_Confidence):
    sector: str
    stance: Stance
    confidence: float
    rationale: str


class StockCall(_Confidence):
    code: str
    company: str
    stance: Stance
    horizon_days: int
    confidence: float
    thesis: str
    evidence: list[str]
    invalidation: str
    stockeye_view: Literal["agrees", "disagrees", "silent"]
    stockeye_note: str
    priced_in: Literal["no", "partly", "yes", "unknown"]

    @field_validator("horizon_days")
    @classmethod
    def _h(cls, v: int) -> int:
        return min(HORIZONS, key=lambda h: abs(h - int(v)))

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        return v.strip().upper()


class WatchItem(BaseModel):
    code: str
    what_to_watch: str


class SourceNote(BaseModel):
    document: str
    key_points: list[str]


class Review(BaseModel):
    headline: str
    market_view: MarketView
    macro: list[MacroItem]
    sectors: list[SectorView]
    calls: list[StockCall]
    watch: list[WatchItem]
    noise: list[str]
    data_gaps: list[str]
    sources_used: list[SourceNote]


def _obj(props: dict, desc: str | None = None) -> dict:
    out = {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}
    if desc:
        out["description"] = desc
    return out


_S = {"type": "string"}
_LS = {"type": "array", "items": _S}
_STANCE = {"type": "string", "enum": ["bullish", "bearish", "neutral"]}
_CONF = {"type": "number", "description": "Probability in % (50-90) that the view is right over its horizon; see ANALYST.md section 7"}
_HZ = {"type": "integer", "description": "Trading days: 5, 20 or 60"}

SCHEMA = _obj({
    "headline": {"type": "string", "description": "One sentence: the most important takeaway today"},
    "market_view": _obj({"stance": _STANCE, "confidence": _CONF, "horizon_days": _HZ, "summary": _S,
                         "drivers": _LS, "risks": _LS}),
    "macro": {"type": "array", "items": _obj({
        "topic": _S, "summary": _S, "impact": {"type": "string", "enum": ["positive", "negative", "mixed", "neutral"]},
        "sectors": _LS, "source": {"type": "string", "description": "Document title and page"}})},
    "sectors": {"type": "array", "items": _obj({"sector": _S, "stance": _STANCE, "confidence": _CONF, "rationale": _S})},
    "calls": {"type": "array", "items": _obj({
        "code": {"type": "string", "description": "Exact DSE code from the code directory"},
        "company": _S, "stance": _STANCE, "horizon_days": _HZ, "confidence": _CONF,
        "thesis": _S, "evidence": {"type": "array", "items": _S, "description": "2-4 points, each with its source"},
        "invalidation": {"type": "string", "description": "Observable event or level that proves the call wrong"},
        "stockeye_view": {"type": "string", "enum": ["agrees", "disagrees", "silent"]},
        "stockeye_note": _S,
        "priced_in": {"type": "string", "enum": ["no", "partly", "yes", "unknown"]}})},
    "watch": {"type": "array", "items": _obj({"code": _S, "what_to_watch": _S})},
    "noise": {"type": "array", "items": _S, "description": "News judged not market-moving, one line each"},
    "data_gaps": _LS,
    "sources_used": {"type": "array", "items": _obj({"document": _S, "key_points": _LS})},
})


# --- request ------------------------------------------------------------------------------------

@dataclass
class ReviewRun:
    review_id: int | None
    review: Review | None
    as_of: str
    doc_ids: list[int]
    usage: dict | None
    request_file: Path | None = None     # dry run: what would have been sent


TASK = """Review the attached research documents for the investor, following your standing instructions.

Documents attached (in order):
{doc_list}

StockEYE context (JSON, data up to {as_of}):
```json
{context}
```

Today is {today}. Write the review as the JSON object the output schema describes:
- calls only where you have a real view (zero is fine); use exact codes from the code directory;
- every evidence point names its source (document title + page, or "StockEYE data");
- put news that won't move prices under `noise`, missing information under `data_gaps`.
"""


def select_docs(db: Database, settings: Settings, doc_ids: list[int] | None) -> pd.DataFrame:
    docs = documents.load_docs(db, doc_ids)
    if doc_ids:
        missing = set(doc_ids) - set(docs["id"])
        if missing:
            raise ValueError(f"Unknown document id(s): {sorted(missing)}")
        return docs
    cutoff = (pd.Timestamp(settings.today()) - pd.Timedelta(days=settings.research.lookback_days)).strftime("%Y-%m-%d")
    docs = docs[~docs["reviewed"] & (docs["published"] >= cutoff)]
    return docs.head(settings.research.max_docs_per_review)


def guide_text(settings: Settings) -> str:
    return settings.resolve(settings.research.guide).read_text(encoding="utf-8")


def build_request(db: Database, settings: Settings, docs: pd.DataFrame, include_pdfs: bool = True) -> tuple[dict, dict]:
    """(request kwargs, StockEYE context). include_pdfs=False leaves out the PDF bytes (for dry runs)."""
    is_table = docs["doc_type"] == "market_review"     # long price tables: lowest priority for context
    context = ctx.build_context(db, settings, [c for cs in docs.loc[~is_table, "codes"] for c in cs],
                                [c for cs in docs.loc[is_table, "codes"] for c in cs])
    guide = guide_text(settings)
    system = [
        {"type": "text", "text": guide},
        {"type": "text", "text": "DSE code directory (CODE: company (sector, category)):\n" + ctx.code_directory(db),
         "cache_control": {"type": "ephemeral"}},     # guide + directory change rarely: cache them
    ]
    content, doc_list = [], []
    for i, d in enumerate(docs.sort_values(["published", "id"]).itertuples(), 1):   # oldest first
        title = f"{d.source or d.filename} ({d.publisher or 'unknown publisher'}), {d.doc_type}, published {d.published}"
        doc_list.append(f"{i}. {title}, {d.pages} pages")
        data = Path(d.file_path).read_bytes() if include_pdfs else b""
        content.append({"type": "document", "title": title[:500],
                        "source": {"type": "base64", "media_type": "application/pdf",
                                   "data": base64.standard_b64encode(data).decode("ascii") if include_pdfs else "<omitted>"}})
    content.append({"type": "text", "text": TASK.format(
        doc_list="\n".join(doc_list), as_of=context["as_of"], today=settings.today().isoformat(),
        context=json.dumps(context, ensure_ascii=False, separators=(",", ":"), default=str))})
    r = settings.research
    request = {
        "model": r.model,
        "max_tokens": r.max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": content}],
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": r.effort, "format": {"type": "json_schema", "schema": SCHEMA}},
        # If a safety classifier declines, retry on Anthropic's recommended fallback model
        "betas": ["server-side-fallback-2026-07-01"],
        "fallbacks": "default",
    }
    return request, context


def has_credentials(settings: Settings) -> bool:
    """An API key in secrets.yaml or the environment (the SDK can also use other credential sources,
    but these are the ones StockEYE documents)."""
    import os

    return bool(settings.anthropic.api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def make_client(settings: Settings):
    import anthropic

    key = settings.anthropic.api_key
    return anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()


def call_claude(client, request: dict) -> tuple[Review, dict]:
    """Stream the request (long input/output) and validate the JSON answer."""
    with client.beta.messages.stream(**request) as stream:
        message = stream.get_final_message()
    if message.stop_reason == "refusal":
        details = getattr(message, "stop_details", None)
        raise RuntimeError(f"The model declined this review ({getattr(details, 'category', None) or 'no category'}).")
    if message.stop_reason == "max_tokens":
        raise RuntimeError("The review was cut off at max_tokens; raise research.max_tokens or review fewer documents.")
    text = "".join(b.text for b in message.content if b.type == "text")
    review = Review.model_validate(json.loads(text))
    u = message.usage
    usage = {k: getattr(u, k, None) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                                                "cache_creation_input_tokens")}
    usage["model"] = message.model
    return review, usage


def run_review(db: Database, settings: Settings, doc_ids: list[int] | None = None, client=None,
               dry_run: bool = False) -> ReviewRun:
    docs = select_docs(db, settings, doc_ids)
    if docs.empty:
        raise ValueError("No documents to review: add some first (research add / research inbox), "
                         f"or pass document ids. Default = unreviewed documents from the last "
                         f"{settings.research.lookback_days} days.")
    ids = docs["id"].astype(int).tolist()
    if dry_run:
        request, context = build_request(db, settings, docs, include_pdfs=False)
        out = settings.resolve(settings.research.store) / f"request-{datetime.now():%Y%m%d-%H%M%S}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(request, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        return ReviewRun(None, None, context["as_of"], ids, None, out)

    request, context = build_request(db, settings, docs)
    review, usage = call_claude(client or make_client(settings), request)
    known = set(db.load_companies()["code"])
    unknown = [c.code for c in review.calls if c.code not in known]
    if unknown:     # never store calls on codes that don't exist
        review.data_gaps.append(f"Calls dropped, unknown codes: {', '.join(unknown)}")
        review.calls = [c for c in review.calls if c.code in known]
    guide_sha = hashlib.sha256(guide_text(settings).encode("utf-8")).hexdigest()[:12]
    with db.conn:
        cur = db.conn.execute(
            "INSERT INTO ai_reviews (created_at, as_of, model, doc_ids, review, usage, guide_sha) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"), context["as_of"], usage.get("model") or request["model"],
             json.dumps(ids), review.model_dump_json(), json.dumps(usage), guide_sha),
        )
    review_id = cur.lastrowid
    ledger.save_calls(db, review_id, context["as_of"], [c.model_dump() for c in review.calls])
    log.info("Review %d saved: %d calls, usage %s", review_id, len(review.calls), usage)
    return ReviewRun(review_id, review, context["as_of"], ids, usage)


def load_reviews(db: Database) -> pd.DataFrame:
    df = pd.read_sql_query("SELECT * FROM ai_reviews ORDER BY id DESC", db.conn)
    for col in ("doc_ids", "review", "usage"):
        df[col] = df[col].map(lambda v: json.loads(v) if v else None)
    return df
