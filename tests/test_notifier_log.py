"""Notifier alert-audit log: every send() call appends one JSON line."""
import json

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
