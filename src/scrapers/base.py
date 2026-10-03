"""Shared scraping primitives: sessions, retries, ld+json parsing."""
import abc
import json
import random
import re
import time
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
    "enter the characters you see",
    "robot check",
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
    def _get(self, url: str, retries: int = 2) -> requests.Response:
        """GET with per-request UA + proxy rotation, exponential backoff."""
        last_exc: Optional[Exception] = None
        for attempt in range(retries + 1):
            headers = {"User-Agent": random.choice(USER_AGENTS)}
            proxies = self.proxy_pool.as_dict() if self.proxy_pool else {}
            try:
                return self.session.get(
                    url, headers=headers, proxies=proxies or None, timeout=self.timeout
                )
            except requests.RequestException as exc:  # timeouts, DNS, proxy errors…
                last_exc = exc
                if attempt < retries:
                    time.sleep(2 ** attempt + random.random())
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
