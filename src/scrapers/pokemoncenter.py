"""pokemoncenter.com — Salesforce Commerce Cloud.

Product pages carry schema.org Product ld+json with offers.availability
(InStock/OutOfStock). SKU is the /product/<sku>/ path segment.

NOTE: pokemoncenter.com hard-blocks datacenter IPs (CloudFront 403), so this
scraper requires residential/rotating proxies to work. The parse logic is
verified against their JSON-LD structure but untested against a live page.
"""
import re

from .base import BaseScraper
from ..models import ProductResult

SKU_RE = re.compile(r"/product/([\w.\-]+)/", re.IGNORECASE)


class PokemonCenterScraper(BaseScraper):
    retailer = "pokemoncenter"

    def check(self, product: dict) -> ProductResult:
        url = product["url"]
        name = product.get("name") or url
        sku = product.get("sku") or self._sku_from_url(url)
        try:
            resp = self._get(url)
        except Exception as exc:
            return ProductResult(self.retailer, name, url, sku, error=f"request failed: {exc}")
        if resp.status_code != 200:
            return ProductResult(self.retailer, name, url, sku, error=f"HTTP {resp.status_code}")
        html = resp.text
        if self._looks_like_botwall(html):
            return ProductResult(self.retailer, name, url, sku, error="bot-challenge page served")
        for node in self._product_nodes(html):
            offers = self._first_offer(node.get("offers"))
            in_stock = self._availability_to_bool(offers.get("availability"))
            price = offers.get("price")
            image = node.get("image")
            if isinstance(image, list):
                image = image[0] if image else None
            if isinstance(image, dict):
                image = image.get("url")
            image_url = image if isinstance(image, str) else None
            if in_stock is None:
                return ProductResult(
                    self.retailer, name, url, sku,
                    price=str(price) if price else None,
                    image_url=image_url,
                    error="Product ld+json found but availability missing",
                )
            return ProductResult(
                self.retailer, name, url, sku, in_stock=in_stock,
                price=str(price) if price else None,
                image_url=image_url,
            )
        return ProductResult(self.retailer, name, url, sku,
                             error="no Product ld+json block found")

    @staticmethod
    def _sku_from_url(url: str):
        match = SKU_RE.search(url)
        return match.group(1) if match else None
