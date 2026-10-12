"""Telegram bot: reads your commands (/bought, /sold, /stop, /holdings, /undo) and replies.

`python -m dse_screener bot` long-polls and answers within seconds (scripts/register_bot_task.ps1
starts it at logon). The 3pm job also reads pending messages before the summary, unless the bot
is running. Only messages from your own chat (telegram.chat_id) are acted on.
"""

from __future__ import annotations

import logging
import time as _time
from datetime import datetime, timezone

from . import holdings, report
from .config import Settings
from .db import Database
from .notify.telegram import TelegramError, TelegramNotifier

log = logging.getLogger(__name__)

OFFSET_KEY = "telegram.offset"
HEARTBEAT_KEY = "telegram.bot_heartbeat"
MENU = [("bought", "PTL 53.7 500: record a buy"), ("sold", "PTL 60: record a sell"),
        ("stop", "PTL 48: set your stop"), ("holdings", "your positions now"),
        ("undo", "remove your last entry"), ("help", "how to use the tracker")]


def handle_text(db: Database, settings: Settings, text: str, ref: str | None = None) -> str:
    """One message -> the reply. Errors become friendly replies, never exceptions."""
    try:
        cmd = holdings.parse(text, settings.today())
        return holdings.apply(db, settings, cmd, source="telegram", source_ref=ref)
    except holdings.CommandError as exc:
        return f"❌ {report._e(str(exc))}"
    except Exception as exc:  # noqa: BLE001
        log.exception("Command failed: %r", text)
        return f"❌ Something went wrong: {report._e(type(exc).__name__)}. Nothing was saved."


def poll_once(db: Database, settings: Settings, tg: TelegramNotifier, wait_s: int = 0) -> int:
    """Fetch and answer pending messages. Returns how many were handled."""
    offset = db.get_state(OFFSET_KEY)
    updates = tg.updates(int(offset) + 1 if offset else None, wait_s)
    handled = 0
    for u in updates:
        msg = u.get("message") or {}
        chat = str((msg.get("chat") or {}).get("id", ""))
        text = (msg.get("text") or "").strip()
        reply = None
        if chat != str(tg.chat_id):
            log.warning("Ignoring a message from chat %s (not telegram.chat_id)", chat)
        elif text:
            reply = handle_text(db, settings, text, ref=f"tg:{u['update_id']}")
            handled += 1
        db.set_state(OFFSET_KEY, str(u["update_id"]))
        if reply:
            tg.send(reply)
    return handled


def bot_running(db: Database, within_s: float = 180) -> bool:
    """True if `bot` polled recently (then the daily job leaves the messages to it)."""
    beat = db.get_state(HEARTBEAT_KEY)
    if not beat:
        return False
    return (datetime.now(timezone.utc) - datetime.fromisoformat(beat)).total_seconds() < within_s


def run(db: Database, settings: Settings, tg: TelegramNotifier, wait_s: int = 50,
        sleep=_time.sleep, stop=lambda: False) -> None:
    try:
        tg.set_commands(MENU)
    except TelegramError as exc:
        log.warning("Couldn't set the command menu: %s", exc)
    log.info("Bot running: send /help to your bot. Ctrl+C to stop.")
    failures = 0
    while not stop():
        db.set_state(HEARTBEAT_KEY, datetime.now(timezone.utc).isoformat(timespec="seconds"))
        try:
            if n := poll_once(db, settings, tg, wait_s):
                log.info("Handled %d message(s)", n)
            failures = 0
        except Exception as exc:  # noqa: BLE001 - network drops, 409 while another poller runs
            failures += 1
            pause = min(5 * failures, 120)
            log.warning("Polling failed (%s), retrying in %ds", exc, pause)
            sleep(pause)
