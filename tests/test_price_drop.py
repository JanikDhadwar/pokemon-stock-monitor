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
    handle_result(_res("$510.00"), state, n, baseline=False)
    assert n.sent == [("price_drop", "$510.00")]
    assert state[URL]["price_drop_alerted"] == "$510.00"


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
    handle_result(_res("$514.00"), state, n, baseline=False)
    assert n.sent == [("price_drop", "$514.00")]
    assert state[URL]["price_drop_alerted"] == "$514.00"


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


# --- Minimum-significance gate (alert-quality) ---------------------------
# A price drop must be at least $1 AND at least 1% below the reference
# price to earn a ping. Real case: on 2026-10-03 the Paldean Fates ETB fired
# five alerts for drops of $0.02–$0.47 on a ~$521 listing. Those are noise.


def test_pocket_change_drop_does_not_alert():
    # The exact 2026-10-03 noise case: $521.64 -> $521.62.
    n = StubNotifier()
    state = _state("$521.64")
    handle_result(_res("$521.62"), state, n, baseline=False)
    assert n.sent == []
    # A suppressed drip must not move the alert floor.
    assert state[URL]["price_drop_alerted"] is None


def test_drop_below_dollar_floor_does_not_alert():
    # $0.49 on a $39.99 item: under the $1 absolute floor.
    n = StubNotifier()
    state = _state("$39.99")
    handle_result(_res("$39.50"), state, n, baseline=False)
    assert n.sent == []


def test_drop_below_percent_floor_does_not_alert():
    # $2.00 on a $521.64 item clears $1 but is only 0.38% — still noise.
    n = StubNotifier()
    state = _state("$521.64")
    handle_result(_res("$519.64"), state, n, baseline=False)
    assert n.sent == []


def test_drop_meeting_both_floors_alerts():
    # $2.00 on a $200.00 item: >= $1 and exactly 1% — qualifies.
    n = StubNotifier()
    state = _state("$200.00")
    handle_result(_res("$198.00"), state, n, baseline=False)
    assert n.sent == [("price_drop", "$198.00")]
    assert state[URL]["price_drop_alerted"] == "$198.00"


def test_suppressed_drip_keeps_floor_for_later_drop():
    # A suppressed dip doesn't move the floor; a later meaningful dip
    # measured against it still fires.
    n = StubNotifier()
    state = _state("$520.69")
    state[URL]["price_drop_alerted"] = "$520.69"
    handle_result(_res("$519.99"), state, n, baseline=False)  # $0.70: suppressed
    assert n.sent == []
    handle_result(_res("$514.00"), state, n, baseline=False)  # $5.99: fires
    assert n.sent == [("price_drop", "$514.00")]
    assert state[URL]["price_drop_alerted"] == "$514.00"
