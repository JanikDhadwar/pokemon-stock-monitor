"""The check_one harness safety net in src/monitor.py.

Every scraper's check() is supposed to never raise (failures land in
ProductResult.error), but a retailer changing its page can still blow up
a parser in a way nobody predicted — a KeyError, a regex on None, a
bad cast. check_one is the last line of defence: it converts the raise
into an UNKNOWN result so one bad retailer can't kill the whole pass
and take every other retailer's alerts down with it. Until now it had
zero tests — the safety net itself was unverified.
"""
import copy

from src.models import ProductResult
from src.monitor import check_one, run_pass, FAIL_STREAKS_KEY

URL1 = "https://example.com/p/1"
URL2 = "https://example.com/p/2"


class ExplodingScraper:
    def check(self, product):
        raise ValueError("boom: unexpected page layout")


class FakeScraper:
    def __init__(self, results):
        self.results = results

    def check(self, product):
        return self.results[product["url"]]


class RecNotifier:
    def __init__(self):
        self.calls = []
        self.cooldowns = {}

    def send(self, event_type, result, extra=""):
        self.calls.append((event_type, result.url))
        self.cooldowns[f"{result.url}|{event_type}"] = 1_700_000_000.0
        return True


def _product(url=URL1):
    return {"retailer": "amazon", "url": url, "name": "Box", "sku": "S1"}


def test_raising_scraper_becomes_unknown_result():
    result = check_one(ExplodingScraper(), _product())
    assert result.in_stock is None
    assert result.error.startswith("harness error: ")
    assert "boom: unexpected page layout" in result.error
    # Identity of the product survives, so the streak + logs name it.
    assert result.retailer == "amazon"
    assert result.name == "Box"
    assert result.url == URL1


def test_raising_scraper_does_not_raise():
    # The whole point: check_one swallows the exception, never re-raises.
    check_one(ExplodingScraper(), _product())  # no pytest.raises needed


def test_healthy_scraper_passes_through_unchanged():
    expected = ProductResult("amazon", "Box", URL1, "S1",
                             in_stock=True, price="$39.99")
    result = check_one(FakeScraper({URL1: expected}), _product())
    assert result is expected


def test_run_pass_survives_a_raising_scraper(monkeypatch):
    """One exploding retailer must not kill the rest of the pass."""
    monkeypatch.setattr("src.monitor.random.uniform", lambda a, b: 0)
    products = [
        {"retailer": "amazon", "url": URL1, "name": "Box 1"},
        {"retailer": "amazon", "url": URL2, "name": "Box 2"},
    ]
    state = {
        URL1: {"name": "Box 1", "retailer": "amazon", "in_stock": False,
               "price": "$39.99", "price_drop_alerted": None,
               "checked_at": "2026-11-10T00:00:00Z"},
        URL2: {"name": "Box 2", "retailer": "amazon", "in_stock": False,
               "price": "$99.99", "price_drop_alerted": None,
               "checked_at": "2026-11-10T00:00:00Z"},
    }
    # URL1's scraper explodes; URL2 restocks normally.
    scrapers = {"amazon": _MixedScraper()}
    notifier = RecNotifier()
    snapshots = []
    run_pass(products, scrapers, state, notifier, baseline=False,
             save_fn=lambda s: snapshots.append(copy.deepcopy(s)))
    # Product 2 was still checked and its restock fired.
    assert notifier.calls == [("restock", URL2)]
    # Product 1's failure was recorded as a streak, not a crash.
    assert state[FAIL_STREAKS_KEY][URL1] == 1
    # Its last-known-good state was left untouched.
    assert state[URL1]["in_stock"] is False
    # State was saved after each product despite the explosion.
    assert len(snapshots) == 3


class _MixedScraper:
    """Explodes for URL1, returns a restock for URL2."""
    def check(self, product):
        if product["url"] == URL1:
            raise RuntimeError("parser blew up on a changed page")
        return ProductResult("amazon", "Box 2", URL2, "S2",
                             in_stock=True, price="$99.99")
