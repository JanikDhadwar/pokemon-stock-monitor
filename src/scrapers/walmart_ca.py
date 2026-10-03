"""walmart.ca — same Salesforce/PerimeterX-fronted platform as walmart.com.

Reuses the US parser (__NEXT_DATA__ first, ld+json fallback); only the
retailer key differs. Prices are CAD — passed through untouched.
"""
from .walmart import WalmartScraper


class WalmartCaScraper(WalmartScraper):
    retailer = "walmart_ca"
