"""amazon.ca — same page structure as amazon.com.

Reuses the US parser (ld+json, then #availability text + displayPrice
fallback); only the retailer key differs. Prices are CAD — passed through
untouched. CAPTCHAs on datacenter IPs are the norm, same as the US site.
"""
from .amazon import AmazonScraper


class AmazonCaScraper(AmazonScraper):
    retailer = "amazon_ca"
