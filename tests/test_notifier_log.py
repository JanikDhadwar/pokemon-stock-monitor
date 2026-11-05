"""Notifier alert-audit log: every send() call appends one JSON line."""
import json

import requests

from src.models import ProductResult
from src.notifier import DiscordNotifier


def _res(**kw):
    base = dict(retailer="amazon", name="Test Box", url="https://example.com/p/1",
                sku="SKU1", in_stock=True, price="$9.99")
    base.update(kw)
    return ProductResult(**base)


def test_dry_run_writes_log_line(tmp_path):
    log = tmp_path / "alerts.log"
    n = DiscordNotifier(webhook_url=None, dry_run=True, log_path=log)  # dry-run: no webhook
    assert n.send("restock", _res()) is True
    entry = json.loads(log.read_text().strip().splitlines()[-1])
    assert entry["event"] == "restock"
    assert entry["retailer"] == "amazon"
    assert entry["name"] == "Test Box"
    assert entry["outcome"] == "dry-run"
    assert entry["ts"]


def test_cooldown_suppression_is_logged(tmp_path):
    log = tmp_path / "alerts.log"
    n = DiscordNotifier(webhook_url=None, dry_run=True, log_path=log)
    assert n.send("restock", _res()) is True
    assert n.send("restock", _res()) is False  # cooldown hit
    lines = log.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["outcome"] == "cooldown-suppressed"


def test_rate_limited_429_retries_after_retry_after(tmp_path, monkeypatch):
    """A Discord 429 is transient, not a rejection: the notifier must honor
    Retry-After and retry instead of failing fast like other 4xx codes."""
    log = tmp_path / "alerts.log"
    calls = []
    sleeps = []

    class FakeResp:
        def __init__(self, status_code, headers=None):
            self.status_code = status_code
            self.headers = headers or {}

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return FakeResp(429, {"Retry-After": "5"})
        return FakeResp(200)

    monkeypatch.setattr("src.notifier.requests.post", flaky)
    monkeypatch.setattr("src.notifier.time.sleep", lambda s: sleeps.append(s))
    n = DiscordNotifier(webhook_url="https://discord.example/webhook", log_path=log)
    assert n.send("restock", _res()) is True
    assert len(calls) == 2
    assert sleeps == [5.0]  # honored Retry-After, not the 1s backoff
    assert json.loads(log.read_text().strip().splitlines()[-1])["outcome"] == "sent"


def test_rate_limited_429_without_header_uses_backoff(tmp_path, monkeypatch):
    """A 429 with no (or a junk) Retry-After header still retries, falling
    back to the exponential backoff instead of crashing or failing fast."""
    log = tmp_path / "alerts.log"
    calls = []
    sleeps = []

    class FakeResp:
        def __init__(self, status_code, headers=None):
            self.status_code = status_code
            self.headers = headers or {}

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return FakeResp(429, {"Retry-After": "not-a-number"})
        return FakeResp(200)

    monkeypatch.setattr("src.notifier.requests.post", flaky)
    monkeypatch.setattr("src.notifier.time.sleep", lambda s: sleeps.append(s))
    n = DiscordNotifier(webhook_url="https://discord.example/webhook", log_path=log)
    assert n.send("restock", _res()) is True
    assert len(calls) == 2
    assert sleeps == [1]  # 2**0 fallback backoff


def test_persistent_429_gives_up_and_keeps_cooldown(tmp_path, monkeypatch):
    """Three straight 429s exhaust the retries, the send fails, and the
    cooldown stamp is restored so the next pass retries promptly."""
    log = tmp_path / "alerts.log"
    calls = []

    class FakeResp:
        status_code = 429
        headers = {"Retry-After": "1"}

    def always_429(*args, **kwargs):
        calls.append(1)
        return FakeResp()

    monkeypatch.setattr("src.notifier.requests.post", always_429)
    monkeypatch.setattr("src.notifier.time.sleep", lambda s: None)
    n = DiscordNotifier(webhook_url="https://discord.example/webhook", log_path=log)
    res = _res()
    assert n.send("restock", res) is False
    assert len(calls) == 3
    assert n.send("restock", res) is False  # cooldown restored, retried again
    assert len(calls) == 6
    assert "429" in json.loads(log.read_text().strip().splitlines()[-1])["outcome"]


def test_failed_send_does_not_consume_cooldown(tmp_path, monkeypatch):
    """A Discord POST failure must not eat the cooldown: the alert never
    reached anyone, so the next pass should retry promptly instead of
    waiting out ALERT_COOLDOWN_SEC."""
    log = tmp_path / "alerts.log"
    calls = []

    def boom(*args, **kwargs):
        calls.append(1)
        raise requests.RequestException("connection reset")

    monkeypatch.setattr("src.notifier.requests.post", boom)
    monkeypatch.setattr("src.notifier.time.sleep", lambda s: None)
    n = DiscordNotifier(webhook_url="https://discord.example/webhook", log_path=log)
    assert n.dry_run is False
    res = _res()
    assert n.send("restock", res) is False
    assert len(calls) == 3  # retried 3x, then gave up
    # Cooldown stamp must be restored: a follow-up send hits the network
    # again instead of being cooldown-suppressed.
    assert n.send("restock", res) is False
    assert len(calls) == 6
    lines = log.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[-1])["outcome"].startswith("failed")
