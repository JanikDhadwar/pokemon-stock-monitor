"""One-shot "retailer went dark" alerts.

When a URL that previously returned real data fails OUTAGE_ALERT_STREAK
consecutive passes, the monitor fires a single Discord `retailer_outage`
alert (not one per pass). URLs that never returned real data — the
expected always-blocked retailers (Pokémon Center, Walmart) and the
costco.ca placeholder — never alert. A recovery fires one
"retailer recovered" ping and clears the flag, so the next outage
alerts again.
"""
from src.models import ProductResult
from src.monitor import (handle_result, FAIL_STREAKS_KEY, OUTAGE_ALERTED_KEY,
                         OUTAGE_ALERT_STREAK)

URL = "https://example.com/p/1"


class RecNotifier:
    """Records sends; returns True like a delivered Discord POST."""
    def __init__(self, ok=True):
        self.calls = []
        self.ok = ok

    def send(self, event_type, result, extra=""):
        self.calls.append((event_type, result.url, extra))
        return self.ok


def _fail(url=URL):
    return ProductResult(retailer="amazon_ca", name="Box", url=url, sku="S",
                         in_stock=None, error="no stock signal (likely bot-walled)")


def _ok(url=URL, price="$99.99"):
    return ProductResult(retailer="amazon_ca", name="Box", url=url, sku="S",
                         in_stock=True, price=price)


def _state_with_last_good(url=URL, **kw):
    last = {"name": "Box", "retailer": "amazon_ca", "in_stock": True,
            "price": "$99.99", "checked_at": "2026-10-22T00:00:00Z"}
    last.update(kw)
    return {url: last}


def _run_fails(n, state, fails=OUTAGE_ALERT_STREAK):
    for _ in range(fails):
        handle_result(_fail(), state, n, baseline=False)


def test_no_outage_alert_before_threshold():
    n, state = RecNotifier(), _state_with_last_good()
    _run_fails(n, state, fails=OUTAGE_ALERT_STREAK - 1)
    assert n.calls == []
    assert URL not in state.get(OUTAGE_ALERTED_KEY, {})


def test_outage_alert_fires_once_at_threshold():
    n, state = RecNotifier(), _state_with_last_good()
    _run_fails(n, state)
    assert len(n.calls) == 1
    event, url, extra = n.calls[0]
    assert event == "retailer_outage"
    assert url == URL
    assert str(OUTAGE_ALERT_STREAK) in extra
    assert "$99.99" in extra  # last-known price is in the alert
    assert URL in state[OUTAGE_ALERTED_KEY]
    # Subsequent passes while the outage continues: no repeat pings.
    handle_result(_fail(), state, n, baseline=False)
    handle_result(_fail(), state, n, baseline=False)
    assert len(n.calls) == 1


def test_never_working_urls_never_alert():
    n, state = RecNotifier(), {}  # no last-known-good state: expected block
    _run_fails(n, state, fails=OUTAGE_ALERT_STREAK + 5)
    assert n.calls == []
    assert state[FAIL_STREAKS_KEY][URL] == OUTAGE_ALERT_STREAK + 5


def test_unknown_last_good_does_not_alert():
    n, state = RecNotifier(), _state_with_last_good(in_stock=None, price=None)
    _run_fails(n, state)
    assert n.calls == []


def test_recovery_clears_flag_and_next_outage_alerts_again():
    n, state = RecNotifier(), _state_with_last_good()
    _run_fails(n, state)
    assert len(n.calls) == 1
    handle_result(_ok(), state, n, baseline=False)
    assert URL not in state.get(FAIL_STREAKS_KEY, {})
    assert URL not in state.get(OUTAGE_ALERTED_KEY, {})
    _run_fails(n, state)
    assert len(n.calls) == 3  # outage, recovery, second outage


def test_recovery_alert_fires_once_with_context():
    n, state = RecNotifier(), _state_with_last_good()
    _run_fails(n, state)
    assert len(n.calls) == 1
    handle_result(_ok(), state, n, baseline=False)
    assert len(n.calls) == 2
    event, url, extra = n.calls[1]
    assert event == "retailer_recovered"
    assert url == URL
    assert str(OUTAGE_ALERT_STREAK) in extra  # how long it was dark
    assert "2026-10-22T00:00:00Z" in extra  # last read before the outage
    # A further successful pass sends nothing more.
    handle_result(_ok(), state, n, baseline=False)
    assert len(n.calls) == 2


def test_no_recovery_alert_without_prior_outage():
    # Same price, same stock as last good: nothing fires at all.
    n, state = RecNotifier(), _state_with_last_good()
    handle_result(_ok(), state, n, baseline=False)
    assert n.calls == []


def test_failed_recovery_send_keeps_flag_and_retries():
    n, state = RecNotifier(), _state_with_last_good()
    _run_fails(n, state)
    assert len(n.calls) == 1
    n.ok = False
    handle_result(_ok(), state, n, baseline=False)
    assert len(n.calls) == 2  # recovery attempted, POST failed
    assert URL in state[OUTAGE_ALERTED_KEY]  # flag kept: retry next pass
    n.ok = True
    handle_result(_ok(), state, n, baseline=False)
    assert len(n.calls) == 3
    assert n.calls[2][0] == "retailer_recovered"
    assert URL not in state.get(OUTAGE_ALERTED_KEY, {})


def test_failed_outage_send_retries_next_pass():
    # A failed Discord POST must not set the flag: the alert is retried on
    # the next pass instead of being swallowed (same philosophy as the
    # Oct 12 failed-POST cooldown fix).
    n, state = RecNotifier(ok=False), _state_with_last_good()
    _run_fails(n, state, fails=OUTAGE_ALERT_STREAK + 2)
    assert len(n.calls) == 3  # retried every pass while failing
    assert URL not in state.get(OUTAGE_ALERTED_KEY, {})
    # When the POST finally succeeds, the flag is set and retries stop.
    n.ok = True
    handle_result(_fail(), state, n, baseline=False)
    assert len(n.calls) == 4
    assert URL in state[OUTAGE_ALERTED_KEY]
    handle_result(_fail(), state, n, baseline=False)
    assert len(n.calls) == 4
