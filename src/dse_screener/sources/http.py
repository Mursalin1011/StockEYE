"""Shared polite HTTP client for all site adapters."""

from __future__ import annotations

import gzip
import logging
import ssl
import time
from pathlib import Path

import requests
import truststore
from requests.adapters import HTTPAdapter

from ..config import HttpConfig

log = logging.getLogger(__name__)


class _SystemTrustAdapter(HTTPAdapter):
    """Verify TLS with the OS certificate store.

    old.dsebd.org omits its intermediate certificate. The OS store can fetch it
    (as browsers do); Python's bundled CA list cannot, so verification would fail.
    """

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        return super().init_poolmanager(*args, **kwargs)


def system_trust_session() -> requests.Session:
    session = requests.Session()
    session.mount("https://", _SystemTrustAdapter())
    return session


class PoliteClient:
    """GET with a minimum delay between requests and exponential-backoff retries."""

    def __init__(self, cfg: HttpConfig, raw_dir: Path | None = None):
        self.cfg = cfg
        self.raw_dir = raw_dir
        self.session = system_trust_session()
        self.session.headers["User-Agent"] = cfg.user_agent
        self._last_request = 0.0

    def get(self, url: str, params: dict | None = None) -> str:
        for attempt in range(1, self.cfg.retries + 1):
            wait = self.cfg.delay_s - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            try:
                self._last_request = time.monotonic()
                resp = self.session.get(url, params=params, timeout=self.cfg.timeout_s)
                resp.raise_for_status()
                return resp.text
            except requests.RequestException as exc:
                if attempt == self.cfg.retries:
                    raise
                log.warning("GET %s failed (%s), retry %d", url, exc, attempt)
                time.sleep(self.cfg.delay_s * 2**attempt)
        raise AssertionError("unreachable")

    def save_raw(self, source: str, name: str, html: str) -> None:
        """Keep a gzipped copy so pages can be re-parsed without re-downloading."""
        if not self.raw_dir:
            return
        folder = self.raw_dir / source
        folder.mkdir(parents=True, exist_ok=True)
        with gzip.open(folder / f"{name}.html.gz", "wt", encoding="utf-8") as f:
            f.write(html)
