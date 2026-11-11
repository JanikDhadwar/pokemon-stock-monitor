"""Per-product state persistence in run_pass.

A pass killed mid-way (service restart — three interrupted runs in the
Nov 7–10 checks.log) used to lose every alert + cooldown from the
products already checked, because state.json was only written at the end
of the pass. The rerun then re-fired the same alerts. run_pass now saves
state after each product, so a kill after product N loses nothing.
"""
import copy

from src.models import ProductResult
from src.monitor import run_pass

URL1 = "https://example.com/p/1"
URL2 = "https://example.com/p/2"


class FakeScraper:
    """Returns a canned result per URL."""
    def __init__(self, results):
        self.results = results

    def check(self, product):
        return self.results[product["url"]]


class RecNotifier:
    """Records sends and stamps cooldowns like the real notifier."""
    def __init__(self):
        self.calls = []
        self.cooldowns = {}

    def send(self, event_type, result, extra=""):
        self.calls.append((event_type, result.url))
        self.cooldowns[f"{result.url}|{event_type}"] = 1_700_000_000.0
        return True


def _products():
    return [
        {"retailer": "amazon", "url": URL1, "name": "Box 1"},
        {"retailer": "amazon", "url": URL2, "name": "Box 2"},
    ]


def _state():
    return {
        URL1: {"name": "Box 1", "retailer": "amazon", "in_stock": False,
               "price": "$39.99", "price_drop_alerted": None,
               "checked_at": "2026-11-10T00:00:00Z"},
        URL2: {"name": "Box 2", "retailer": "amazon", "in_stock": True,
               "price": "$99.99", "price_drop_alerted": None,
               "checked_at": "2026-11-10T00:00:00Z"},
    }


def _results():
    return {
        URL1: ProductResult("amazon", "Box 1", URL1, "S1",
                            in_stock=True, price="$39.99"),  # restock!
        URL2: ProductResult("amazon", "Box 2", URL2, "S2",
                            in_stock=True, price="$99.99"),  # no change
    }


def _run(monkeypatch, products=None, state=None, notifier=None, saves=None):
    monkeypatch.setattr("src.monitor.random.uniform", lambda a, b: 0)
    scrapers = {"amazon": FakeScraper(_results())}
    state = _state() if state is None else state
    notifier = RecNotifier() if notifier is None else notifier
    snapshots = [] if saves is None else saves
    run_pass(products if products is not None else _products(),
             scrapers, state, notifier, baseline=False,
             save_fn=lambda s: snapshots.append(copy.deepcopy(s)))
    return state, notifier, snapshots


def test_state_saved_after_each_product(monkeypatch):
    _, notifier, snapshots = _run(monkeypatch)
    assert notifier.calls == [("restock", URL1)]
    # One save after each checked product (2) + the final end-of-pass save.
    assert len(snapshots) == 3
    first = snapshots[0]
    # The very first save already holds product 1's restock AND its
    # cooldown stamp — a kill right after product 1 loses nothing.
    assert first[URL1]["in_stock"] is True
    assert f"{URL1}|restock" in first["_cooldowns"]
    # Product 2 hasn't been checked yet at that point.
    assert first[URL2]["in_stock"] is True  # unchanged from prior state
    assert first[URL2]["checked_at"] == "2026-11-10T00:00:00Z"


def test_rerun_after_midpass_kill_does_not_realert(monkeypatch):
    _, _, snapshots = _run(monkeypatch)
    # Simulate: the pass was killed right after product 1 saved. The
    # rerun loads exactly what that save wrote.
    state2 = snapshots[0]
    notifier2 = RecNotifier()
    run_pass(_products(), {"amazon": FakeScraper(_results())}, state2,
             notifier2, baseline=False,
             save_fn=lambda s: None)
    assert notifier2.calls == []  # no duplicate restock for product 1


def test_placeholder_and_unknown_retailer_do_not_save(monkeypatch):
    monkeypatch.setattr("src.monitor.random.uniform", lambda a, b: 0)
    products = [
        {"retailer": "amazon", "url": "https://example.com/placeholder",
         "name": "Placeholder", "verified": False},
        {"retailer": "nosuch", "url": "https://example.com/x", "name": "X"},
        {"retailer": "amazon", "url": URL1, "name": "Box 1"},
    ]
    snapshots = []
    run_pass(products, {"amazon": FakeScraper(_results())}, _state(),
             RecNotifier(), baseline=False,
             save_fn=lambda s: snapshots.append(copy.deepcopy(s)))
    # Only the one real checked product saves mid-pass, plus the final save.
    assert len(snapshots) == 2
