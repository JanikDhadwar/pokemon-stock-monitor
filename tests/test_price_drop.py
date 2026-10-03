"""price_drop must not re-fire on a flickering price; cooldowns must persist."""
import time

from src.models import ProductResult
from src.monitor import handle_result
from src.notifier import DiscordNotifier

URL = "https://example.com/p/1"


class StubNotifier:
    """Minimal stand-in: records sends, always 'succeeds' (no cooldown)."""

    def __init__(self):
        self.sent = []

    def send(self, event_type, result, extra=""):
        self.sent.append((event_type, result.price))
        return True


def _res(price, in_stock=True):
    return ProductResult(retailer="amazon", name="Box", url=URL, sku="S",
                         in_stock=in_stock, price=price)


def _state(price):
    return {URL: {"name": "Box", "retailer": "amazon", "in_stock": True,
                  "price": price, "checked_at": "t"}}


def test_genuine_drop_alerts_and_records_low():
    n, state = StubNotifier(), _state("$521.64")
    handle_result(_res("$520.69"), state, n, baseline=False)
    assert n.sent == [("price_drop", "$520.69")]
    assert state[URL]["price_drop_alerted"] == "$520.69"


def test_same_price_does_not_refire():
    n = StubNotifier()
    state = _state("$520.69")
    state[URL]["price_drop_alerted"] = "$520.69"
    handle_result(_res("$520.69"), state, n, baseline=False)
    assert n.sent == []


def test_flicker_up_then_down_does_not_refire():
    n = StubNotifier()
    state = _state("$520.69")
    state[URL]["price_drop_alerted"] = "$520.69"
    # price flickers up (no alert on a rise)...
    handle_result(_res("$537.99"), state, n, baseline=False)
    assert n.sent == []
    # ...then back down to the already-alerted low: still no alert.
    handle_result(_res("$520.69"), state, n, baseline=False)
    assert n.sent == []


def test_new_low_below_alerted_price_fires():
    n = StubNotifier()
    state = _state("$520.69")
    state[URL]["price_drop_alerted"] = "$520.69"
    handle_result(_res("$519.99"), state, n, baseline=False)
    assert n.sent == [("price_drop", "$519.99")]
    assert state[URL]["price_drop_alerted"] == "$519.99"


def test_cooldown_survives_across_notifier_instances():
    url, event = URL, "restock"
    n1 = DiscordNotifier(webhook_url=None, dry_run=True, cooldown_sec=3600)
    assert n1._cooldown_ok(url, event) is True
    assert n1._cooldown_ok(url, event) is False  # in-memory, same instance
    # A fresh instance seeded with the persisted dict still suppresses.
    n2 = DiscordNotifier(webhook_url=None, dry_run=True, cooldown_sec=3600,
                         cooldowns=n1.cooldowns)
    assert n2._cooldown_ok(url, event) is False
    # ...but an expired entry allows again.
    n2.cooldowns[f"{url}|{event}"] = time.time() - 7200
    assert n2._cooldown_ok(url, event) is True
