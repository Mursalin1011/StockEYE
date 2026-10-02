"""Research documents: add from a link, a file or the inbox folder; recognise, date, extract text, find stocks.

Copies live under research.store (git-ignored). Broker reports are usually marked "not for public
distribution": they stay on this PC and are only sent to the Claude API for the review.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import yaml
from pydantic import BaseModel

from ..config import Settings
from ..db import Database

log = logging.getLogger(__name__)

DOC_TYPES = ("newsflash", "market_review", "macro", "company", "sector", "other")
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_DATE_IN_NAME = re.compile(rf"({MONTHS})[-_ ]?(\d{{1,2}})[-_, ]+(\d{{4}})", re.I)
_EPOCH_MS = re.compile(r"(?<!\d)(1[6-9]\d{11})(?!\d)")       # S3-style upload stamp, e.g. 1790826012847
_CODE_TOKEN = re.compile(r"(?<![A-Za-z0-9-])[A-Z][A-Z0-9&-]{1,14}(?![A-Za-z0-9-])")
_GENERIC = {"the", "of", "and", "bangladesh", "national", "general", "insurance", "bank", "life", "limited",
            "ltd", "plc", "company", "co", "industries", "industry", "first", "islami", "islamic", "prime",
            "mutual", "fund", "finance", "investment", "investments", "securities", "holdings", "group"}
_SUFFIXES = {"plc", "ltd", "limited", "company", "co", "the", "inc"}


class SourceRule(BaseModel):
    name: str
    publisher: str = "unknown"
    doc_type: str = "other"
    match: str


class SourcesFile(BaseModel):
    ignore_codes: list[str] = []
    sources: list[SourceRule] = []


@dataclass
class AddResult:
    doc_id: int
    created: bool          # False = same file (by content) was already imported
    filename: str
    doc_type: str
    published: str | None
    codes: list[str]


def load_sources(settings: Settings) -> SourcesFile:
    path = settings.resolve(settings.research.sources)
    if not path.exists():
        return SourcesFile()
    return SourcesFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def classify(name_or_url: str, rules: list[SourceRule]) -> SourceRule | None:
    for rule in rules:
        if re.search(rule.match, name_or_url, re.I):
            return rule
    return None


def published_date(name: str, fallback: date | None = None) -> date | None:
    """From the file name ('...-October-1-2026-...'), else an upload timestamp in the name, else fallback."""
    m = _DATE_IN_NAME.search(name.replace("%20", " "))
    if m:
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y").date()
        except ValueError:
            pass
    m = _EPOCH_MS.search(name)
    if m:
        return datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc).date()
    return fallback


def extract_text(data: bytes) -> tuple[int, str]:
    """(pages, text). Pages are separated by form feeds. Chart-heavy PDFs extract poorly; the review
    sends the PDF itself to Claude, so this text is only for search and finding stock codes."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return len(reader.pages), "\f".join((p.extract_text() or "") for p in reader.pages)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s.lower())).strip()


def name_index(companies: pd.DataFrame) -> dict[str, str]:
    """Normalised company-name phrases -> code: the full name without PLC/Ltd, plus its first two words
    when they are distinctive (e.g. 'ibn sina') and unique to one company."""
    full, prefix_count, prefixes = {}, {}, {}
    for r in companies.itertuples():
        words = [w for w in _norm(str(r.name or "")).split() if w not in _SUFFIXES]
        if len(words) >= 2:
            full[" ".join(words)] = r.code
            p = " ".join(words[:2])
            prefix_count[p] = prefix_count.get(p, 0) + 1
            prefixes[p] = r.code
    for p, code in prefixes.items():
        if prefix_count[p] == 1 and not (set(p.split()) & _GENERIC) and len(p) >= 6:
            full.setdefault(p, code)
    return full


def mentioned_codes(text: str, companies: pd.DataFrame, ignore: list[str] | None = None) -> list[str]:
    """DSE codes written as codes ('PTL 85.7') or as company names ('One Bank')."""
    known = set(companies["code"]) - set(ignore or [])
    found = {t for t in _CODE_TOKEN.findall(text) if t in known}
    flat = f" {_norm(text)} "
    for phrase, code in name_index(companies).items():
        if f" {phrase} " in flat:
            found.add(code)
    return sorted(found)


def _safe_name(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    return name[:150] or "document.pdf"


def add_document(db: Database, settings: Settings, data: bytes, filename: str, url: str | None = None,
                 doc_type: str | None = None) -> AddResult:
    if not data.startswith(b"%PDF"):
        raise ValueError(f"{filename}: not a PDF")
    max_bytes = settings.research.max_pdf_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise ValueError(f"{filename}: {len(data) / 1e6:.1f} MB is over the {settings.research.max_pdf_mb:g} MB limit")
    if doc_type and doc_type not in DOC_TYPES:
        raise ValueError(f"doc_type must be one of {', '.join(DOC_TYPES)}")
    sha = hashlib.sha256(data).hexdigest()
    row = db.conn.execute("SELECT id, filename, doc_type, published, codes FROM research_docs WHERE sha256 = ?",
                          (sha,)).fetchone()
    if row:
        return AddResult(row[0], False, row[1], row[2], row[3], json.loads(row[4]))

    sources = load_sources(settings)
    rule = classify(url or filename, sources.sources)
    pages, text = extract_text(data)
    published = published_date(url or filename) or published_date(filename) or settings.today()
    codes = mentioned_codes(text, db.load_companies(), sources.ignore_codes)
    store = settings.resolve(settings.research.store)
    store.mkdir(parents=True, exist_ok=True)
    path = store / f"{published:%Y-%m-%d}_{sha[:8]}_{_safe_name(filename)}"
    path.write_bytes(data)
    with db.conn:
        cur = db.conn.execute(
            "INSERT INTO research_docs (sha256, url, file_path, filename, source, publisher, doc_type, published, "
            "pages, text, codes, added_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sha, url, str(path), filename, rule.name if rule else None, rule.publisher if rule else None,
             doc_type or (rule.doc_type if rule else "other"), published.isoformat(), pages, text,
             json.dumps(codes), datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
    log.info("Added %s (%s, %s, %d pages, %d stocks mentioned)", filename, doc_type or (rule.doc_type if rule else "other"),
             published, pages, len(codes))
    return AddResult(cur.lastrowid, True, filename, doc_type or (rule.doc_type if rule else "other"),
                     published.isoformat(), codes)


def add_url(db: Database, settings: Settings, url: str, doc_type: str | None = None) -> AddResult:
    """Download a PDF link (https only) and add it."""
    from ..sources.http import system_trust_session

    if not url.lower().startswith("https://"):
        raise ValueError("Only https:// links are accepted")
    session = system_trust_session()
    session.headers["User-Agent"] = settings.http.user_agent
    max_bytes = int(settings.research.max_pdf_mb * 1024 * 1024)
    with session.get(url, timeout=settings.http.timeout_s, stream=True) as resp:
        resp.raise_for_status()
        chunks, size = [], 0
        for chunk in resp.iter_content(1 << 16):
            size += len(chunk)
            if size > max_bytes:
                raise ValueError(f"{url}: larger than {settings.research.max_pdf_mb:g} MB")
            chunks.append(chunk)
    filename = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1] or "document.pdf"
    return add_document(db, settings, b"".join(chunks), filename, url=url, doc_type=doc_type)


def add_file(db: Database, settings: Settings, path: Path, doc_type: str | None = None) -> AddResult:
    return add_document(db, settings, path.read_bytes(), path.name, doc_type=doc_type)


def scan_inbox(db: Database, settings: Settings) -> list[AddResult]:
    """Import every PDF in the inbox folder (already-imported files are recognised by content)."""
    inbox = settings.resolve(settings.research.inbox)
    if not inbox.exists():
        return []
    out = []
    for path in sorted(inbox.glob("*.pdf")):
        try:
            out.append(add_file(db, settings, path))
        except ValueError as e:
            log.warning("Skipped %s: %s", path.name, e)
    return out


def load_docs(db: Database, ids: list[int] | None = None) -> pd.DataFrame:
    q = "SELECT id, url, file_path, filename, source, publisher, doc_type, published, pages, codes, added_at FROM research_docs"
    params: list = []
    if ids:
        q += f" WHERE id IN ({', '.join('?' * len(ids))})"
        params = list(ids)
    df = pd.read_sql_query(q + " ORDER BY published DESC, id DESC", db.conn, params=params)
    df["codes"] = df["codes"].map(json.loads)
    reviewed = set()
    for (doc_ids,) in db.conn.execute("SELECT doc_ids FROM ai_reviews"):
        reviewed |= set(json.loads(doc_ids))
    df["reviewed"] = df["id"].isin(reviewed)
    return df
