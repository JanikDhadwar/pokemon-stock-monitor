"""costco.ca — same Akamai-fronted platform as costco.com.

Reuses the US ld+json availability parser; only the retailer key differs.
Prices are CAD — passed through untouched. Expect bot-wall / sign-in
errors on datacenter IPs, same as the US site.
"""
from .costco import CostcoScraper


class CostcoCaScraper(CostcoScraper):
    retailer = "costco_ca"
