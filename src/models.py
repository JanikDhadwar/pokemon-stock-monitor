"""Shared data models for scrape results."""
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class StockStatus(str, Enum):
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    UNKNOWN = "unknown"


@dataclass
class ProductResult:
    """Outcome of checking one product. Never raises — failures land in `error`."""

    retailer: str
    name: str
    url: str
    sku: Optional[str] = None
    in_stock: Optional[bool] = None  # True / False / None (unknown)
    price: Optional[str] = None
    image_url: Optional[str] = None
    error: Optional[str] = None

    @property
    def status(self) -> StockStatus:
        if self.in_stock is True:
            return StockStatus.IN_STOCK
        if self.in_stock is False:
            return StockStatus.OUT_OF_STOCK
        return StockStatus.UNKNOWN
