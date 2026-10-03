"""Live smoke test — one product per retailer.

Informational only: prints a results table and always exits 0. Retailer blocks
are expected on datacenter IPs; they show up as errors in the table, which is
the honest result (see TEST_RESULTS.md).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import yaml  # noqa: E402

from src.proxies import ProxyPool  # noqa: E402
from src.scrapers import SCRAPERS  # noqa: E402


def main() -> None:
    with open("config/products.yaml", encoding="utf-8") as fh:
        products = yaml.safe_load(fh)["products"]
    seen = {}
    for p in products:
        seen.setdefault(p["retailer"], p)

    pool = ProxyPool()
    print(f"proxies: {len(pool)} | timeout 20s | {len(seen)} retailers")
    print(f"{'retailer':<14}{'in_stock':<10}{'price':<12}{'name / error'}")
    print("-" * 90)
    for retailer, product in seen.items():
        scraper = SCRAPERS[retailer](pool)
        try:
            r = scraper.check(product)
        except Exception as exc:  # noqa: BLE001 — harness-level catch
            print(f"{retailer:<14}{'HARNESS-ERR':<10}{'':<12}{exc}")
            continue
        detail = (r.error or r.name or "")[:52]
        print(f"{retailer:<14}{str(r.in_stock):<10}{(r.price or ''):<12}{detail}")
    print("-" * 90)
    print("done.")


if __name__ == "__main__":
    main()
