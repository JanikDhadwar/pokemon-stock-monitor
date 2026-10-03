#!/usr/bin/env python3
"""Poll loop: check every product, diff against state.json, fire Discord alerts.

Usage:
    python -m src.monitor --once --dry-run   # single pass, print alerts
    python -m src.monitor --once              # single pass, live alerts
    python -m src.monitor                     # poll loop
    python -m src.monitor --discover "elite trainer box"
"""
import argparse
import json
import os
import random
import re
import time
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

from .models import ProductResult
from .notifier import DiscordNotifier
from .proxies import ProxyPool
from .scrapers import SCRAPERS

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "products.yaml"
STATE_PATH = ROOT / "state.json"

PRODUCT_LINK_RE = re.compile(
    r'href="((?:/[a-z]{2}-[a-z]{2})?/product/[\w.\-]+/[\w.\-]+/?)"', re.IGNORECASE
)


def load_products() -> list:
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh).get("products", [])


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def check_one(scraper, product: dict) -> ProductResult:
    """Harness-level safety net — scrapers shouldn't raise, but just in case."""
    try:
        return scraper.check(product)
    except Exception as exc:
        return ProductResult(
            retailer=product.get("retailer", "?"),
            name=product.get("name") or product.get("url", "?"),
            url=product.get("url", ""),
            error=f"harness error: {exc}",
        )


def _price_to_float(value) -> float:
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except (ValueError, TypeError, AttributeError):
        return float("inf")


def handle_result(result: ProductResult, state: dict, notifier: DiscordNotifier,
                  baseline: bool) -> None:
    tag = f"[{result.retailer}]"
    if result.error and result.in_stock is None:
        # Unknown — never alert, and never overwrite last-known-good state.
        print(f"{tag} {result.name}: UNKNOWN ({result.error})")
        return
    print(f"{tag} {result.name}: stock={result.in_stock} price={result.price}"
          + (f" !! {result.error}" if result.error else ""))
    prev = state.get(result.url)
    if prev is None:
        # First sighting of this URL. On a fresh state.json this is just the
        # baseline (no spam); on later runs it's a genuinely new listing.
        if not baseline:
            notifier.send("new_listing", result)
    else:
        if prev.get("in_stock") in (False, None) and result.in_stock is True:
            notifier.send("restock", result)
        elif prev.get("in_stock") is True and result.in_stock is False:
            notifier.send("out_of_stock", result)
        old_price, new_price = prev.get("price"), result.price
        old_f, new_f = _price_to_float(old_price), _price_to_float(new_price)
        if (old_price and new_price and old_f != float("inf")
                and new_f != float("inf") and new_f < old_f):
            notifier.send("price_drop", result, extra=f"{old_price} → {new_price}")
    state[result.url] = {
        "name": result.name,
        "retailer": result.retailer,
        "in_stock": result.in_stock,
        "price": result.price,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def discover(query: str, notifier: DiscordNotifier) -> None:
    """Best-effort scan of pokemoncenter.com search for listings not in products.yaml."""
    pool = ProxyPool()
    scraper = SCRAPERS["pokemoncenter"](pool)
    slug = re.sub(r"\s+", "-", query.strip().lower())
    candidates = [
        f"https://www.pokemoncenter.com/search/{slug}",
        f"https://www.pokemoncenter.com/en-ca/search/{slug}",
    ]
    html: Optional[str] = None
    for url in candidates:
        try:
            resp = scraper._get(url)
            if resp.status_code == 200 and "/product/" in resp.text:
                html = resp.text
                print(f"[discover] using {url}")
                break
            print(f"[discover] {url} -> HTTP {resp.status_code}")
        except Exception as exc:
            print(f"[discover] {url} failed: {exc}")
    if not html:
        print("[discover] could not load a search page (bot wall?)")
        return

    def norm(u: str) -> str:
        return re.sub(r"^/[a-z]{2}-[a-z]{2}(?=/product/)", "", u).rstrip("/")

    found = set()
    for match in PRODUCT_LINK_RE.finditer(html):
        found.add("https://www.pokemoncenter.com" + match.group(1))
    known = {norm(p["url"]) for p in load_products()}
    new_urls = sorted({u for u in found if norm(u) not in known})
    print(f"[discover] {len(found)} product links, {len(new_urls)} not tracked")
    for url in new_urls[:25]:
        print("  NEW:", url)
        notifier.send("new_listing", ProductResult("pokemoncenter", url, url))


def main() -> None:
    ap = argparse.ArgumentParser(description="Pokémon TCG stock monitor → Discord")
    ap.add_argument("--once", action="store_true", help="single pass, then exit")
    ap.add_argument("--dry-run", action="store_true", help="print alerts instead of POSTing")
    ap.add_argument("--discover", metavar="QUERY",
                    help='scan pokemoncenter search for new listings, e.g. "elite trainer box"')
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    poll_interval = int(os.getenv("POLL_INTERVAL_SEC", "60"))
    cooldown = int(os.getenv("ALERT_COOLDOWN_SEC", "1800"))

    pool = ProxyPool()
    print(f"[init] proxies configured: {len(pool)}")
    notifier = DiscordNotifier(os.getenv("DISCORD_WEBHOOK_URL"),
                               dry_run=args.dry_run, cooldown_sec=cooldown)
    if notifier.dry_run:
        print("[init] dry-run mode: alerts print to console, nothing is posted")

    if args.discover:
        discover(args.discover, notifier)
        return

    products = load_products()
    print(f"[init] tracking {len(products)} products")
    scrapers = {name: cls(pool) for name, cls in SCRAPERS.items()}

    baseline = not STATE_PATH.exists()
    if baseline:
        print("[init] no state.json — this pass records a silent baseline (no new-listing spam)")
    state = load_state()

    def run_pass() -> None:
        for product in products:
            retailer = product.get("retailer")
            scraper = scrapers.get(retailer)
            if scraper is None:
                print(f"[skip] no scraper for retailer={retailer!r}")
                continue
            result = check_one(scraper, product)
            handle_result(result, state, notifier, baseline)
            time.sleep(random.uniform(1.0, 3.0))  # politeness jitter between products
        save_state(state)
        print(f"[pass] done — state saved ({len(state)} urls tracked)")

    if args.once:
        run_pass()
        return
    while True:
        run_pass()
        time.sleep(poll_interval + random.uniform(0, poll_interval * 0.25))


if __name__ == "__main__":
    main()
