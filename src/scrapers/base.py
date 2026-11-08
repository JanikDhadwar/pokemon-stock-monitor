"""Shared scraping primitives: sessions, retries, ld+json parsing."""
import abc
import json
import random
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Iterator, Optional

import requests

from ..models import ProductResult

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
]

BASE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

LD_JSON_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)

CAPTCHA_HINTS = (
    "captcha",
    "are you a robot",
    "not a robot",  # Amazon: "make sure you're not a robot"
    "enter the characters you see",
    "robot check",
    "automated access to amazon data",  # Amazon's 503 "dog page" footer
)


class BaseScraper(abc.ABC):
    """One scraper per retailer.

    ``check()`` must never raise — encode every failure as a ProductResult
    with ``error`` set, so one bad retailer can't kill the monitor loop.
    """

    retailer: str = "base"

    def __init__(self, proxy_pool=None, timeout: int = 20):
        self.proxy_pool = proxy_pool
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(BASE_HEADERS)

    @abc.abstractmethod
    def check(self, product: dict) -> ProductResult:
        """Check one product dict (from products.yaml). Must not raise."""

    # -- HTTP ---------------------------------------------------------
    # Statuses worth one retry after a wait instead of an instant failure:
    # 429 (rate-limited — Costco has flapped on this since Nov 5, 2026) and
    # 503 (Amazon's bot-wall "dog page" is also a 503, so a wait-and-retry
    # costs nothing there either). Retry-After is honored when present.
    RETRYABLE_STATUSES = (429, 503)
    # A server asking us to wait an hour is not a request we honor mid-pass:
    # the hosted job re-runs every 5 min anyway, so cap the in-pass wait.
    MAX_RETRY_AFTER_SEC = 30

    @staticmethod
    def _retry_after_seconds(resp) -> Optional[float]:
        """Seconds the server asks us to wait, or None if it doesn't say.

        Accepts a plain seconds value ("120") or an HTTP-date. Returns None
        for a missing, garbage, or already-past value.
        """
        headers = getattr(resp, "headers", None) or {}
        raw = headers.get("Retry-After")
        if raw is None:
            return None
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            pass
        try:
            when = parsedate_to_datetime(str(raw))
        except (TypeError, ValueError, OverflowError):
            return None
        if when is None:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())

    def _get(self, url: str, retries: int = 2) -> requests.Response:
        """GET with per-request UA + proxy rotation, exponential backoff.

        Transport errors retry with backoff (as before). A 429/503 response
        now also retries once per attempt budget, waiting out Retry-After
        (capped at MAX_RETRY_AFTER_SEC) instead of handing the rate-limit
        straight to the caller as a failed pass — previously every Costco
        429 during a limit window burned a fail streak and risked a
        spurious outage alert, even though the next pass minutes later
        usually succeeded.
        """
        last_exc: Optional[Exception] = None
        for attempt in range(retries + 1):
            headers = {"User-Agent": random.choice(USER_AGENTS)}
            proxies = self.proxy_pool.as_dict() if self.proxy_pool else {}
            try:
                resp = self.session.get(
                    url, headers=headers, proxies=proxies or None, timeout=self.timeout
                )
            except requests.RequestException as exc:  # timeouts, DNS, proxy errors…
                last_exc = exc
                if attempt < retries:
                    time.sleep(2 ** attempt + random.random())
                continue
            if resp.status_code in self.RETRYABLE_STATUSES and attempt < retries:
                wait = self._retry_after_seconds(resp)
                if wait is None:
                    wait = 2 ** attempt + random.random()
                else:
                    wait = min(wait, self.MAX_RETRY_AFTER_SEC) + random.random()
                time.sleep(wait)
                continue
            return resp
        raise last_exc  # type: ignore[misc]

    # -- schema.org ld+json -------------------------------------------
    def _ld_json_blocks(self, html: str) -> Iterator[dict]:
        for match in LD_JSON_RE.finditer(html):
            try:
                data = json.loads(match.group(1).strip())
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        yield item
            elif isinstance(data, dict):
                yield data

    def _product_nodes(self, html: str) -> Iterator[dict]:
        """Yield schema.org Product nodes (handles @graph wrappers)."""
        for block in self._ld_json_blocks(html):
            nodes = block.get("@graph") if isinstance(block.get("@graph"), list) else [block]
            for node in nodes:
                if isinstance(node, dict) and node.get("@type") == "Product":
                    yield node

    @staticmethod
    def _first_offer(offers) -> dict:
        if isinstance(offers, dict):
            return offers
        if isinstance(offers, list) and offers:
            return offers[0] if isinstance(offers[0], dict) else {}
        return {}

    @staticmethod
    def _availability_to_bool(availability) -> Optional[bool]:
        if not availability:
            return None
        a = str(availability).lower()
        if "instock" in a:
            return True
        if "outofstock" in a:
            return False
        if "preorder" in a or "limitedavailability" in a or "instoreonly" in a:
            return True  # orderable in some form
        return None

    @staticmethod
    def _looks_like_botwall(html: str) -> bool:
        low = html.lower()
        return any(hint in low for hint in CAPTCHA_HINTS)
