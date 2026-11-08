"""Rate-limit retry tests for BaseScraper._get — offline, no network.

Costco US has flapped on HTTP 429 since Nov 5, 2026: the old _get returned
a 429 immediately, so every pass inside a limit window burned a fail streak
(and risked a spurious outage alert) even though the next pass minutes later
usually succeeded. _get must now wait out Retry-After (capped) and retry
429/503 responses inside its normal retry budget, while leaving other
statuses untouched.
"""
import sys
from datetime import datetime, timedelta, timezone
from email.utils import formatdate
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.scrapers.base import BaseScraper  # noqa: E402
from src.scrapers.costco import CostcoScraper  # noqa: E402


class FakeResponse:
    def __init__(self, status_code=200, text="", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


def make_scraper(responses, monkeypatch):
    """CostcoScraper whose session.get yields `responses` in order."""
    scraper = CostcoScraper(proxy_pool=None)
    calls = []
    sleeps = []
    queue = list(responses)

    def fake_get(url, headers=None, proxies=None, timeout=None):
        calls.append(url)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    scraper.session.get = fake_get
    monkeypatch.setattr("src.scrapers.base.time.sleep", sleeps.append)
    monkeypatch.setattr("src.scrapers.base.random.random", lambda: 0.0)
    return scraper, calls, sleeps


def test_429_with_retry_after_waits_then_succeeds(monkeypatch):
    scraper, calls, sleeps = make_scraper(
        [FakeResponse(429, headers={"Retry-After": "5"}),
         FakeResponse(200, "<html/>")],
        monkeypatch)
    resp = scraper._get("https://example.com/p/1")
    assert resp.status_code == 200
    assert len(calls) == 2
    assert sleeps == [5.0]


def test_429_without_retry_after_uses_backoff(monkeypatch):
    scraper, calls, sleeps = make_scraper(
        [FakeResponse(429), FakeResponse(200, "<html/>")],
        monkeypatch)
    resp = scraper._get("https://example.com/p/1")
    assert resp.status_code == 200
    assert len(calls) == 2
    assert sleeps == [1.0]  # 2**0 + 0 jitter


def test_429_retry_after_capped_at_30s(monkeypatch):
    # A server asking for an hour must not stall the pass: cap at 30s.
    scraper, calls, sleeps = make_scraper(
        [FakeResponse(429, headers={"Retry-After": "3600"}),
         FakeResponse(200, "<html/>")],
        monkeypatch)
    resp = scraper._get("https://example.com/p/1")
    assert resp.status_code == 200
    assert sleeps == [30.0]


def test_429_retry_after_http_date(monkeypatch):
    when = datetime.now(timezone.utc) + timedelta(seconds=20)
    scraper, calls, sleeps = make_scraper(
        [FakeResponse(429, headers={"Retry-After": formatdate(when.timestamp(), usegmt=True)}),
         FakeResponse(200, "<html/>")],
        monkeypatch)
    resp = scraper._get("https://example.com/p/1")
    assert resp.status_code == 200
    assert len(sleeps) == 1
    assert 18.0 <= sleeps[0] <= 20.0  # ~20s, minus the moments spent running


def test_429_persists_returns_last_response_not_raise(monkeypatch):
    scraper, calls, sleeps = make_scraper(
        [FakeResponse(429), FakeResponse(429), FakeResponse(429)],
        monkeypatch)
    resp = scraper._get("https://example.com/p/1")
    assert resp.status_code == 429
    assert len(calls) == 3  # initial + 2 retries, then give up gracefully
    assert len(sleeps) == 2


def test_503_retries_like_429(monkeypatch):
    scraper, calls, sleeps = make_scraper(
        [FakeResponse(503), FakeResponse(200, "<html/>")],
        monkeypatch)
    resp = scraper._get("https://example.com/p/1")
    assert resp.status_code == 200
    assert len(calls) == 2


def test_403_does_not_retry(monkeypatch):
    scraper, calls, sleeps = make_scraper([FakeResponse(403)], monkeypatch)
    resp = scraper._get("https://example.com/p/1")
    assert resp.status_code == 403
    assert len(calls) == 1
    assert sleeps == []


def test_transport_error_still_retries(monkeypatch):
    scraper, calls, sleeps = make_scraper(
        [requests.ConnectionError("dns boom"), FakeResponse(200, "<html/>")],
        monkeypatch)
    resp = scraper._get("https://example.com/p/1")
    assert resp.status_code == 200
    assert len(calls) == 2
    assert sleeps == [1.0]


def test_garbage_retry_after_falls_back_to_backoff(monkeypatch):
    scraper, calls, sleeps = make_scraper(
        [FakeResponse(429, headers={"Retry-After": "not-a-date"}),
         FakeResponse(200, "<html/>")],
        monkeypatch)
    resp = scraper._get("https://example.com/p/1")
    assert resp.status_code == 200
    assert sleeps == [1.0]


def test_costco_429_then_live_page_parses(monkeypatch):
    """End to end through the Costco parser: 429, then a real page."""
    html = ('<html><head><script type="application/ld+json">'
            '{"@type": "Product", "offers": {"availability": '
            '"https://schema.org/OutOfStock", "price": "39.99"}}</script>'
            "</head></html>")
    scraper, calls, sleeps = make_scraper(
        [FakeResponse(429, headers={"Retry-After": "2"}),
         FakeResponse(200, html)],
        monkeypatch)
    result = scraper.check({
        "retailer": "costco", "name": "Mini Tins",
        "url": "https://www.costco.com/p/-/x/1", "sku": "X",
    })
    assert result.in_stock is False
    assert result.price == "39.99"
    assert result.error is None
    assert len(calls) == 2
