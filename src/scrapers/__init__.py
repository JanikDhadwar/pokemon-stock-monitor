"""Retailer scraper registry."""
from .amazon import AmazonScraper
from .amazon_ca import AmazonCaScraper
from .costco import CostcoScraper
from .costco_ca import CostcoCaScraper
from .pokemoncenter import PokemonCenterScraper
from .walmart import WalmartScraper
from .walmart_ca import WalmartCaScraper

SCRAPERS = {
    "pokemoncenter": PokemonCenterScraper,
    "walmart": WalmartScraper,
    "costco": CostcoScraper,
    "amazon": AmazonScraper,
    "walmart_ca": WalmartCaScraper,
    "costco_ca": CostcoCaScraper,
    "amazon_ca": AmazonCaScraper,
}

__all__ = ["SCRAPERS"]
