"""Unverified placeholders must never be fetched, and their junk fail
streaks must not linger in state.json (regression: the costco.ca homepage
placeholder accrued a 5000+ fail streak by being fetched every 5 min)."""
from src.monitor import (
    drop_placeholder_streaks,
    is_unverified_placeholder,
)

PLACEHOLDER = {
    "retailer": "costco_ca",
    "name": "Placeholder",
    "url": "https://www.costco.ca/",
    "verified": False,
}
REAL = {
    "retailer": "costco",
    "name": "Real listing",
    "url": "https://www.costco.com/p/-/example/123",
    "verified": True,
}
LEGACY_NO_FLAG = {
    "retailer": "amazon",
    "name": "Pre-flag listing",
    "url": "https://www.amazon.com/dp/EXAMPLE",
}


def test_explicit_false_is_placeholder():
    assert is_unverified_placeholder(PLACEHOLDER) is True


def test_verified_true_is_tracked():
    assert is_unverified_placeholder(REAL) is False


def test_missing_flag_defaults_to_tracked():
    # Real listings predate the `verified` flag; a missing flag must not
    # silently drop a product from the check loop.
    assert is_unverified_placeholder(LEGACY_NO_FLAG) is False


def test_drop_placeholder_streaks_removes_only_placeholders():
    state = {"_fail_streaks": {
        "https://www.costco.ca/": 5076,
        "https://www.costco.com/p/-/example/123": 3,
        "https://www.amazon.com/dp/EXAMPLE": 42,
    }}
    dropped = drop_placeholder_streaks(state, [PLACEHOLDER, REAL, LEGACY_NO_FLAG])
    assert dropped == 1
    assert state["_fail_streaks"] == {
        "https://www.costco.com/p/-/example/123": 3,
        "https://www.amazon.com/dp/EXAMPLE": 42,
    }


def test_drop_placeholder_streaks_empty_state_is_noop():
    assert drop_placeholder_streaks({}, [PLACEHOLDER]) == 0
    assert drop_placeholder_streaks({"_fail_streaks": {}}, [PLACEHOLDER]) == 0
