"""walmart.com — best effort.

Tries the embedded __NEXT_DATA__ product JSON first, falls back to ld+json.
Walmart runs PerimeterX and aggressively bot-walls datacenter IPs; without
residential proxies expect challenge pages (reported as errors, never guessed).
"""
import json
import re

from .base import BaseScraper
from ..models import ProductResult

NEXT_DATA_RE = re.compile(
    r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)


class WalmartScraper(BaseScraper):
    retailer = "walmart"

    def check(self, product: dict) -> ProductResult:
        url = product["url"]
        name = product.get("name") or url
        sku = product.get("sku")
        try:
            resp = self._get(url)
        except Exception as exc:
            return ProductResult(self.retailer, name, url, sku, error=f"request failed: {exc}")
        if resp.status_code != 200:
            return ProductResult(self.retailer, name, url, sku, error=f"HTTP {resp.status_code}")
        html = resp.text
        if self._looks_like_botwall(html) or "px-captcha" in html.lower():
            return ProductResult(self.retailer, name, url, sku,
                                 error="bot-challenge page served")
        result = self._from_next_data(html, name, url, sku)
        if result is not None:
            return result
        return self._from_ld_json(html, name, url, sku)

    def _from_next_data(self, html: str, name: str, url: str, sku):
        match = NEXT_DATA_RE.search(html)
        if not match:
            return None
        try:
            data = json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            return None
        prod = data
        for key in ("props", "pageProps", "initialData", "data", "product"):
            prod = prod.get(key) if isinstance(prod, dict) else None
            if prod is None:
                return None
        in_stock = None
        status = str(prod.get("availabilityStatus") or "").upper()
        if "IN_STOCK" in status:
            in_stock = True
        elif "OUT_OF_STOCK" in status:
            in_stock = False
        if in_stock is None and isinstance(prod.get("available"), bool):
            in_stock = prod["available"]
        if in_stock is None and isinstance(prod.get("canAddToCart"), bool):
            in_stock = prod["canAddToCart"]
        price = None
        price_info = prod.get("priceInfo")
        if isinstance(price_info, dict):
            current = price_info.get("currentPrice")
            if isinstance(current, dict):
                price = current.get("price")
        image = prod.get("imageUrl") or prod.get("image")
        if in_stock is None and price is None:
            return None  # let the caller fall back to ld+json
        return ProductResult(
            self.retailer, name, url, sku or prod.get("id"),
            in_stock=in_stock,
            price=str(price) if price else None,
            image_url=image if isinstance(image, str) else None,
            error=None if in_stock is not None else "availability unclear in __NEXT_DATA__",
        )

    def _from_ld_json(self, html: str, name: str, url: str, sku):
        for node in self._product_nodes(html):
            offers = self._first_offer(node.get("offers"))
            in_stock = self._availability_to_bool(offers.get("availability"))
            price = offers.get("price")
            return ProductResult(
                self.retailer, name, url, sku, in_stock=in_stock,
                price=str(price) if price else None,
                error=None if in_stock is not None else "availability not found",
            )
        return ProductResult(self.retailer, name, url, sku,
                             error="no usable product data (likely bot-walled)")
