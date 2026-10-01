"""Delivery channels. Each has `send(text_html)`; email can be added alongside Telegram."""

from .telegram import TelegramNotifier, find_chat_ids

__all__ = ["TelegramNotifier", "find_chat_ids"]
