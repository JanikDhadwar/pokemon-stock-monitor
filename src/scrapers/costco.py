"""costco.com — ld+json availability, best effort.

Costco uses Akamai Bot Manager and frequently requires sign-in for price and
stock. Expect in_stock=None with an explanatory error on datacenter IPs;
residential proxies are the realistic fix.
"""
from .base import BaseScraper
from ..models import ProductResult


class CostcoScraper(BaseScraper):
    retailer = "costco"

    def check(self, product: dict) -> ProductResult:
        url = product["url"]
        name = product.get("name") or url
        sku = product.get("sku")
        try:
            resp = self._get(url)
        except Exception as exc:
            return ProductResult(self.retailer, name, url, sku, error=f"request failed: {exc}")
        if resp.status_code in (401, 403):
            return ProductResult(
                self.retailer, name, url, sku,
                error=f"HTTP {resp.status_code} — bot wall / sign-in required",
            )
        if resp.status_code == 429:
            # Costco has flapped on HTTP 429 since Nov 5, 2026: the in-pass
            # retries in BaseScraper._get already waited out Retry-After
            # (capped at 30s), so by the time we see a 429 here the limit
            # window is still open. A bare "HTTP 429" reads like a hard
            # failure in cron logs and in the outage alert's "Latest error"
            # line — name it as the transient rate-limit it is.
            return ProductResult(
                self.retailer, name, url, sku,
                error="HTTP 429 — rate-limited (transient, retries next pass)",
            )
        if resp.status_code != 200:
            return ProductResult(self.retailer, name, url, sku, error=f"HTTP {resp.status_code}")
        html = resp.text
        low = html.lower()
        if self._looks_like_botwall(html) or ("akamai" in low and "request blocked" in low):
            return ProductResult(self.retailer, name, url, sku,
                                 error="bot-challenge page served")
        for node in self._product_nodes(html):
            offers = self._first_offer(node.get("offers"))
            in_stock = self._availability_to_bool(offers.get("availability"))
            price = offers.get("price")
            image = node.get("image")
            if isinstance(image, list):
                image = image[0] if image else None
            return ProductResult(
                self.retailer, name, url, sku, in_stock=in_stock,
                price=str(price) if price else None,
                image_url=image if isinstance(image, str) else None,
                error=None if in_stock is not None else "availability not exposed (JS/bot wall likely)",
            )
        return ProductResult(self.retailer, name, url, sku,
                             error="no Product ld+json (page likely bot-walled)")
