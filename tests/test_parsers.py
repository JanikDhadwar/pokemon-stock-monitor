"""Offline parser unit tests — no network access.

Each test feeds a fixture HTML file (tests/fixtures/) to a scraper with its
HTTP layer stubbed out, then asserts on the parsed ProductResult. Covers all
7 scrapers: in-stock, out-of-stock, bot-wall, and missing-data cases, plus a
"request failure never raises" check per scraper and CA-subclass wiring.
"""
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.scrapers import SCRAPERS  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"

PRODUCT = {
    "retailer": "test",
    "name": "Test Product",
    "url": "https://example.com/product/1",
    "sku": "SKU1",
}


class FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def make_scraper(cls, html: str = "", status_code: int = 200, exc=None):
    """Build a scraper whose _get() is stubbed: returns html or raises exc."""
    scraper = cls(proxy_pool=None)

    def fake_get(url, retries=2):
        if exc is not None:
            raise exc
        return FakeResponse(html, status_code)

    scraper._get = fake_get
    return scraper


def check(cls, fixture: str, status_code: int = 200, **overrides):
    product = dict(PRODUCT, **overrides)
    return make_scraper(cls, load(fixture), status_code).check(product)


# ---------------------------------------------------------------- pokemoncenter
class TestPokemonCenter:
    cls = SCRAPERS["pokemoncenter"]

    def test_in_stock(self):
        r = check(self.cls, "pokemoncenter_instock.html")
        assert r.in_stock is True
        assert r.price == "59.99"
        assert r.error is None
        assert r.retailer == "pokemoncenter"

    def test_out_of_stock(self):
        r = check(self.cls, "pokemoncenter_outofstock.html")
        assert r.in_stock is False
        assert r.price == "59.99"

    def test_botwall_403(self):
        r = check(self.cls, "pokemoncenter_botwall.html", status_code=403)
        assert r.in_stock is None
        assert r.error is not None and "403" in r.error

    def test_no_ld_json(self):
        r = check(self.cls, "pokemoncenter_nodata.html")
        assert r.in_stock is None
        assert r.error is not None


# --------------------------------------------------------------------- walmart
class TestWalmart:
    cls = SCRAPERS["walmart"]

    def test_in_stock_next_data(self):
        r = check(self.cls, "walmart_instock_nextdata.html")
        assert r.in_stock is True
        assert r.price == "49.99"
        assert r.error is None

    def test_out_of_stock_next_data(self):
        r = check(self.cls, "walmart_outofstock_nextdata.html")
        assert r.in_stock is False
        assert r.price == "49.99"

    def test_ld_json_fallback(self):
        # No __NEXT_DATA__ on the page: parser must fall back to ld+json.
        r = check(self.cls, "walmart_ldjson_fallback.html")
        assert r.in_stock is False
        assert r.price == "186.77"

    def test_botwall_perimeterx(self):
        r = check(self.cls, "walmart_botwall.html")
        assert r.in_stock is None
        assert r.error is not None and "bot-challenge" in r.error

    def test_no_data(self):
        r = check(self.cls, "walmart_nodata.html")
        assert r.in_stock is None
        assert r.error is not None


# ---------------------------------------------------------------------- costco
class TestCostco:
    cls = SCRAPERS["costco"]

    def test_in_stock(self):
        r = check(self.cls, "costco_instock.html")
        assert r.in_stock is True
        assert r.price == "39.99"
        assert r.error is None

    def test_out_of_stock(self):
        r = check(self.cls, "costco_outofstock.html")
        assert r.in_stock is False
        assert r.price == "39.99"

    def test_botwall_403(self):
        r = check(self.cls, "costco_botwall.html", status_code=403)
        assert r.in_stock is None
        assert r.error is not None and "403" in r.error

    def test_no_ld_json(self):
        r = check(self.cls, "costco_nodata.html")
        assert r.in_stock is None
        assert r.error is not None


# ---------------------------------------------------------------------- amazon
class TestAmazon:
    cls = SCRAPERS["amazon"]

    def test_in_stock_availability_span(self):
        r = check(self.cls, "amazon_instock.html")
        assert r.in_stock is True
        assert r.price == "$199.67"

    def test_out_of_stock_availability_span(self):
        r = check(self.cls, "amazon_outofstock.html")
        assert r.in_stock is False
        assert r.price == "$537.99"

    def test_ld_json_path(self):
        r = check(self.cls, "amazon_ldjson.html")
        assert r.in_stock is True
        assert r.price == "64.99"

    def test_captcha_page(self):
        r = check(self.cls, "amazon_captcha.html")
        assert r.in_stock is None
        assert r.error is not None and "CAPTCHA" in r.error

    def test_no_signal(self):
        r = check(self.cls, "amazon_nosignal.html")
        assert r.in_stock is None
        assert r.error is not None


# ------------------------------------------------- never raises, all scrapers
@pytest.mark.parametrize("retailer,cls", sorted(SCRAPERS.items()))
def test_request_failure_never_raises(retailer, cls):
    """A dead network must produce an error result, never an exception."""
    scraper = make_scraper(cls, exc=requests.ConnectionError("dns boom"))
    product = dict(PRODUCT, retailer=retailer)
    result = scraper.check(product)  # must not raise
    assert result.in_stock is None
    assert result.error is not None and "request failed" in result.error
    assert result.retailer == retailer


# ------------------------------------------------- canadian subclass wiring
@pytest.mark.parametrize(
    "retailer,fixture,expected_stock,expected_price",
    [
        ("walmart_ca", "walmart_instock_nextdata.html", True, "49.99"),
        ("walmart_ca", "walmart_outofstock_nextdata.html", False, "49.99"),
        ("costco_ca", "costco_instock.html", True, "39.99"),
        ("costco_ca", "costco_outofstock.html", False, "39.99"),
        ("amazon_ca", "amazon_ldjson.html", True, "64.99"),
        ("amazon_ca", "amazon_outofstock.html", False, "$537.99"),
    ],
)
def test_ca_scraper_parses_like_us(retailer, fixture, expected_stock, expected_price):
    cls = SCRAPERS[retailer]
    result = make_scraper(cls, load(fixture)).check(dict(PRODUCT, retailer=retailer))
    assert result.retailer == retailer
    assert result.in_stock is expected_stock
    assert result.price == expected_price
