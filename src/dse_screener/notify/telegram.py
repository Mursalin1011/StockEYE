"""Telegram Bot API over plain HTTPS (no extra dependency)."""

from __future__ import annotations

import logging

from ..sources.http import system_trust_session

log = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"
MAX_LEN = 4000   # Telegram's limit is 4096 characters per message


class TelegramError(RuntimeError):
    pass


def _call(session, token: str, method: str, **payload) -> dict:
    resp = session.post(API.format(token=token, method=method), json=payload, timeout=30)
    data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    if not resp.ok or not data.get("ok"):
        # Never log the token: it is part of the URL
        raise TelegramError(f"Telegram {method} failed: HTTP {resp.status_code} {data.get('description', '')}")
    return data["result"]


def split_message(text: str, limit: int = MAX_LEN) -> list[str]:
    """Split on blank lines (between picks), then on lines, so HTML tags never break."""
    chunks, cur = [], ""
    for block in text.split("\n\n"):
        candidate = f"{cur}\n\n{block}" if cur else block
        if len(candidate) <= limit:
            cur = candidate
            continue
        if cur:
            chunks.append(cur)
        cur = ""
        for line in block.split("\n"):
            candidate = f"{cur}\n{line}" if cur else line
            if len(candidate) > limit and cur:
                chunks.append(cur)
                candidate = line
            cur = candidate
    if cur:
        chunks.append(cur)
    return chunks


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str):
        if not bot_token or not chat_id:
            raise TelegramError(
                "Telegram is not set up: put bot_token in config/secrets.yaml, message your bot, "
                "then run `python -m dse_screener telegram-setup`"
            )
        self.token, self.chat_id = bot_token, chat_id
        self.session = system_trust_session()

    def send(self, text_html: str) -> int:
        """Send (split if long). Returns the number of messages sent."""
        parts = split_message(text_html)
        for part in parts:
            _call(self.session, self.token, "sendMessage", chat_id=self.chat_id, text=part,
                  parse_mode="HTML", disable_web_page_preview=True)
        log.info("Telegram: sent %d message(s)", len(parts))
        return len(parts)


def find_chat_ids(bot_token: str) -> list[dict]:
    """Chats that have messaged the bot recently: [{id, name, type}]."""
    updates = _call(system_trust_session(), bot_token, "getUpdates")
    seen = {}
    for u in updates:
        chat = (u.get("message") or u.get("channel_post") or {}).get("chat")
        if chat:
            name = chat.get("title") or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
            seen[chat["id"]] = {"id": str(chat["id"]), "name": name or chat.get("username", ""), "type": chat["type"]}
    return list(seen.values())
