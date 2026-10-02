"""The 22:30 job: import new research PDFs, score matured AI calls, review what's new, send to Telegram.

Quiet when there is nothing new: Telegram only hears about a review, a missing API key with
documents waiting, or a failure (the CLI sends that one).
"""

from __future__ import annotations

import logging
from typing import Callable

from ..config import Settings
from ..db import Database
from ..report import build_notice
from . import documents, ledger, render, review

log = logging.getLogger(__name__)


def run_evening(db: Database, settings: Settings, deliver: Callable[[str], object], client=None) -> str:
    """Returns the outcome: nothing_new | no_key | sent."""
    added = [r for r in documents.scan_inbox(db, settings) if r.created]
    log.info("Inbox: %d new document(s)", len(added))
    try:
        log.info("Scored %d matured AI call(s)", ledger.score_calls(db, settings))
    except Exception:  # noqa: BLE001 - scoring must not block the review
        log.exception("Scoring AI calls failed")

    docs = review.select_docs(db, settings, None)
    if docs.empty:
        log.info("No unreviewed documents from the last %d days: nothing to do", settings.research.lookback_days)
        return "nothing_new"
    if client is None and not review.has_credentials(settings):
        deliver(build_notice(
            "🤖 AI review skipped",
            f"{len(docs)} new research document(s) are waiting, but there is no Anthropic API key. "
            "Add anthropic.api_key to config/secrets.yaml (see secrets.example.yaml).",
        ))
        log.warning("No Anthropic API key; %d document(s) waiting", len(docs))
        return "no_key"

    run = review.run_review(db, settings, client=client)
    titles = documents.load_docs(db, run.doc_ids)
    deliver(render.telegram_html(run.review, run.as_of, titles["source"].fillna(titles["filename"]).tolist()))
    log.info("Review #%d sent: %d calls, usage %s", run.review_id, len(run.review.calls), run.usage)
    return "sent"
