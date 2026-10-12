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
