"""Consecutive check failures are tracked per URL in state['_fail_streaks'].

A retailer outage (e.g. amazon.ca bot-walling the VM) must be visible in
state.json without grepping cron logs; a single recovery clears the streak.
"""
from src.models import ProductResult
from src.monitor import handle_result, FAIL_STREAKS_KEY

URL = "https://example.com/p/1"
URL2 = "https://example.com/p/2"


class StubNotifier:
    def send(self, event_type, result, extra=""):
        return True


def _fail(url=URL):
    return ProductResult(retailer="amazon_ca", name="Box", url=url, sku="S",
                         in_stock=None, error="no stock signal (likely bot-walled)")


def _ok(url=URL):
    return ProductResult(retailer="amazon_ca", name="Box", url=url, sku="S",
                         in_stock=True, price="$99.99")


def test_failures_build_a_streak():
    n, state = StubNotifier(), {}
    handle_result(_fail(), state, n, baseline=False)
    handle_result(_fail(), state, n, baseline=False)
    handle_result(_fail(), state, n, baseline=False)
    assert state[FAIL_STREAKS_KEY][URL] == 3


def test_success_clears_the_streak():
    n, state = StubNotifier(), {FAIL_STREAKS_KEY: {URL: 5}}
    handle_result(_ok(), state, n, baseline=False)
    assert URL not in state[FAIL_STREAKS_KEY]


def test_streaks_are_per_url():
    n, state = StubNotifier(), {}
    handle_result(_fail(URL), state, n, baseline=False)
    handle_result(_fail(URL2), state, n, baseline=False)
    handle_result(_fail(URL), state, n, baseline=False)
    assert state[FAIL_STREAKS_KEY][URL] == 2
    assert state[FAIL_STREAKS_KEY][URL2] == 1


def test_failure_does_not_touch_last_known_good_state():
    n, state = StubNotifier(), {
        URL: {"name": "Box", "retailer": "amazon_ca", "in_stock": True,
              "price": "$99.99", "checked_at": "t"}}
    handle_result(_fail(), state, n, baseline=False)
    assert state[URL]["price"] == "$99.99"
    assert state[URL]["in_stock"] is True
