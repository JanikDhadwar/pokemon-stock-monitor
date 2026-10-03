"""amazon.com — best effort.

Amazon serves CAPTCHAs to datacenter IPs almost universally; without
residential proxies expect in_stock=None with an explanatory error.
Tries ld+json first, then the #availability text as a fallback.
"""
import re

from .base import BaseScraper
from ..models import ProductResult

AVAILABILITY_RE = re.compile(
    r'id="availability"[^>]*>.*?<span[^>]*>(.*?)</span>',
    re.DOTALL | re.IGNORECASE,
)
TAG_RE = re.compile(r"<[^>]+>")
# Embedded JSON blobs often carry the buy-box price even when ld+json lacks it.
DISPLAY_PRICE_RE = re.compile(r'"displayPrice"\s*:\s*"([^"]+)"')


class AmazonScraper(BaseScraper):
    retailer = "amazon"

    def check(self, product: dict) -> ProductResult:
        url = product["url"]
        name = product.get("name") or url
        sku = product.get("sku") or self._asin_from_url(url)
        try:
            resp = self._get(url)
        except Exception as exc:
            return ProductResult(self.retailer, name, url, sku, error=f"request failed: {exc}")
        if resp.status_code != 200:
            return ProductResult(self.retailer, name, url, sku, error=f"HTTP {resp.status_code}")
        html = resp.text
        if self._looks_like_botwall(html):
            return ProductResult(self.retailer, name, url, sku,
                                 error="CAPTCHA / bot-check page served")
        for node in self._product_nodes(html):
            offers = self._first_offer(node.get("offers"))
            in_stock = self._availability_to_bool(offers.get("availability"))
            price = offers.get("price") or self._display_price(html)
            if in_stock is not None or price:
                return ProductResult(
                    self.retailer, name, url, sku, in_stock=in_stock,
                    price=str(price) if price else None,
                )
        match = AVAILABILITY_RE.search(html)
        if match:
            text = TAG_RE.sub("", match.group(1)).strip().lower()
            price = self._display_price(html)
            if "in stock" in text:
                return ProductResult(self.retailer, name, url, sku, in_stock=True,
                                     price=price)
            if "out of stock" in text or "currently unavailable" in text:
                return ProductResult(self.retailer, name, url, sku, in_stock=False,
                                     price=price)
        return ProductResult(self.retailer, name, url, sku,
                             error="no stock signal (likely bot-walled)")

    @staticmethod
    def _display_price(html: str):
        match = DISPLAY_PRICE_RE.search(html)
        return match.group(1).strip() if match else None

    @staticmethod
    def _asin_from_url(url: str):
        match = re.search(r"/dp/([A-Z0-9]{10})", url)
        return match.group(1) if match else None
