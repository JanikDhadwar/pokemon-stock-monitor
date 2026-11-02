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
LOCK_PATH = ROOT / "monitor.lock"


def acquire_singleton_lock(lock_path: Path = None):
    """Best-effort single-instance guard.

    lock_path defaults to the module-level LOCK_PATH (resolved lazily so tests
    can monkeypatch it).

    Returns an open file handle that holds a non-blocking exclusive lock for
    the life of the process, or None if another monitor process is already
    running. Without this, two overlapping --once passes (e.g. a stalled
    pass still alive when cron fires the next one) each load the same stale
    state/cooldowns, both fire the same alert, and both write state.json —
    that was the Oct 8 duplicate price-drop ping.

    Uses fcntl.flock, which releases automatically on process exit, so a
    crashed run can never leave a stale lock behind. On platforms without
    fcntl (Windows) there is no locking API to use, so we proceed
    unguarded — interactive Windows runs are single-pass anyway.
    """
    if lock_path is None:
        lock_path = LOCK_PATH
    try:
        import fcntl
    except ImportError:
        return open(lock_path, "a", encoding="utf-8")
    fh = open(lock_path, "a", encoding="utf-8")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh

# Alert-quality gate: a price drop only earns a Discord ping when it is at
# least this many dollars AND this percent below the reference price.
# Third-party listings flicker by cents constantly; pocket-change moves are
# noise, not deals. Both are env-overridable.
MIN_PRICE_DROP_ABS = float(os.getenv("MIN_PRICE_DROP_ABS", "1.0"))
MIN_PRICE_DROP_PCT = float(os.getenv("MIN_PRICE_DROP_PCT", "1.0"))

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


FAIL_STREAKS_KEY = "_fail_streaks"
OUTAGE_ALERTED_KEY = "_outage_alerted"

# Alert-quality: a tracked URL that previously returned real data and then
# fails this many consecutive passes gets one Discord "retailer outage"
# ping. Expected always-blocked retailers (Pokémon Center, Walmart — never
# returned data) never qualify, and expected outages don't re-ping every
# pass. Default 288 = 24h at the hosted 5-minute check cadence. When the
# URL returns real data again, handle_result() fires one matching
# "retailer recovered" ping and clears the flag.
OUTAGE_ALERT_STREAK = int(os.getenv("OUTAGE_ALERT_STREAK", "288"))


def is_unverified_placeholder(product: dict) -> bool:
    """True only when a product is explicitly marked verified: false.

    Missing `verified` defaults to tracked: every real listing predates the
    flag, and only an explicit false means "placeholder, not a real page".
    """
    return product.get("verified") is False


def drop_placeholder_streaks(state: dict, products: list) -> int:
    """Drop fail-streak entries for unverified placeholder products.

    A placeholder (e.g. the costco.ca homepage, tracked until someone finds
    a real costco.ca product URL) fails every pass by design, so its streak
    grows forever and pollutes the "which retailers are down" read of the
    streak data — same rot prune_stale_fail_streaks fixes for removed URLs,
    except placeholders are still listed in products.yaml, so that prune
    never touches them. Returns the number of dropped entries.
    """
    streaks = state.get(FAIL_STREAKS_KEY)
    if not streaks:
        return 0
    placeholders = {p.get("url") for p in products if is_unverified_placeholder(p)}
    dead = [u for u in streaks if u in placeholders]
    for u in dead:
        del streaks[u]
    return len(dead)


def prune_stale_fail_streaks(state: dict, tracked_urls: set) -> int:
    """Drop fail-streak entries for URLs no longer in products.yaml.

    A removed product's streak would otherwise sit in state.json forever
    (its URL is never checked again, so it never clears), misleading the
    "which retailers are down" read of the streak data. Returns the number
    of pruned entries.
    """
    streaks = state.get(FAIL_STREAKS_KEY)
    if not streaks:
        return 0
    dead = [u for u in streaks if u not in tracked_urls]
    for u in dead:
        del streaks[u]
    return len(dead)


def _maybe_alert_retailer_outage(result: ProductResult, state: dict,
                                 notifier: DiscordNotifier, streak: int) -> None:
    """One-shot Discord alert when a previously-working retailer goes dark.

    Fires only when all of these hold:
      - the consecutive-failure streak crossed OUTAGE_ALERT_STREAK,
      - the URL has a last-known-good read (real in_stock value) — expected
        always-blocked retailers (Pokémon Center, Walmart, the costco.ca
        placeholder) have never returned data and never qualify,
      - we haven't already alerted for this outage (flag lives in
        state["_outage_alerted"], cleared on the next successful pass).

    The flag is set only after a successful send(): a failed Discord POST
    retries on the next pass (matching the failed-POST cooldown philosophy)
    instead of swallowing the alert.
    """
    if streak < OUTAGE_ALERT_STREAK:
        return
    alerted = state.setdefault(OUTAGE_ALERTED_KEY, {})
    if result.url in alerted:
        return
    last_good = state.get(result.url) or {}
    if last_good.get("in_stock") not in (True, False):
        return
    extra = (f"{streak} consecutive failed checks — no stock signal. "
             f"Last good read: {last_good.get('checked_at')} "
             f"(stock={last_good.get('in_stock')}, price={last_good.get('price')}). "
             f"Latest error: {result.error}")
    if notifier.send("retailer_outage", result, extra=extra):
        alerted[result.url] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def handle_result(result: ProductResult, state: dict, notifier: DiscordNotifier,
                  baseline: bool) -> None:
    tag = f"[{result.retailer}]"
    if result.error and result.in_stock is None:
        # Unknown — never alert, and never overwrite last-known-good state.
        # But record the failure streak so a retailer outage (e.g. amazon.ca
        # bot-walling the VM) is visible in state.json without grepping
        # cron logs: url -> consecutive failed passes.
        streaks = state.setdefault(FAIL_STREAKS_KEY, {})
        streak = streaks.get(result.url, 0) + 1
        streaks[result.url] = streak
        print(f"{tag} {result.name}: UNKNOWN ({result.error})"
              + (f" [fail streak: {streak}]" if streak > 1 else ""))
        _maybe_alert_retailer_outage(result, state, notifier, streak)
        return
    # Success clears any accumulated fail streak for this URL. If an outage
    # alert is outstanding for it, this is a recovery: fire a one-shot
    # "retailer recovered" ping — the mirror of the outage alert. Without
    # it, Janik only ever hears that a retailer went dark, never that it
    # came back (e.g. an amazon.ca listing quietly readable again). The
    # flag clears only after a successful send, so a failed Discord POST
    # retries on the next successful pass instead of being swallowed.
    streaks = state.get(FAIL_STREAKS_KEY)
    streak_before = streaks.get(result.url, 0) if streaks else 0
    if streaks and result.url in streaks:
        del streaks[result.url]
    alerted = state.get(OUTAGE_ALERTED_KEY) or {}
    outage_since = alerted.get(result.url)
    print(f"{tag} {result.name}: stock={result.in_stock} price={result.price}"
          + (f" !! {result.error}" if result.error else ""))
    prev = state.get(result.url)
    if outage_since and prev is not None:
        bits = []
        if streak_before:
            bits.append(f"back online after {streak_before} consecutive failed checks")
        else:
            bits.append("back online")
        bits.append(f"outage alerted {outage_since}")
        if prev.get("checked_at"):
            bits.append(f"last read before the outage: {prev.get('checked_at')} "
                        f"(stock={prev.get('in_stock')}, price={prev.get('price')})")
        if notifier.send("retailer_recovered", result, extra=". ".join(bits) + "."):
            del alerted[result.url]
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
        # Compare against the lowest price we've already alerted on, not just
        # the last seen price: a flickering price (up then back down to the
        # same value) must not re-fire the same drop.
        alerted_f = _price_to_float(prev.get("price_drop_alerted") or old_price)
        if (old_price and new_price and old_f != float("inf")
                and new_f != float("inf") and new_f < min(old_f, alerted_f)):
            floor = min(old_f, alerted_f)
            drop = floor - new_f
            # Significance gate: pocket-change moves never ping. A drop must
            # be at least MIN_PRICE_DROP_ABS dollars AND MIN_PRICE_DROP_PCT
            # percent below the reference price. A suppressed drip does not
            # move the floor, so the next pass re-measures against it —
            # only a genuinely meaningful single-pass move fires.
            if (drop >= MIN_PRICE_DROP_ABS
                    and drop >= floor * MIN_PRICE_DROP_PCT / 100.0):
                if notifier.send("price_drop", result,
                                 extra=f"{old_price} → {new_price}"):
                    prev["price_drop_alerted"] = new_price
            else:
                print(f"{tag} {result.name}: price dip {old_price} → {new_price} "
                      f"below alert threshold, skipped")
    state[result.url] = {
        "name": result.name,
        "retailer": result.retailer,
        "in_stock": result.in_stock,
        "price": result.price,
        "price_drop_alerted": prev.get("price_drop_alerted") if prev else None,
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

    # Single-instance guard: if another monitor process is mid-pass, bail out
    # instead of double-alerting and clobbering its state writes.
    lock = acquire_singleton_lock()
    if lock is None:
        print("[lock] another monitor instance is already running — exiting")
        return

    poll_interval = int(os.getenv("POLL_INTERVAL_SEC", "60"))
    cooldown = int(os.getenv("ALERT_COOLDOWN_SEC", "1800"))

    pool = ProxyPool()
    print(f"[init] proxies configured: {len(pool)}")

    baseline = not STATE_PATH.exists()
    if baseline:
        print("[init] no state.json — this pass records a silent baseline (no new-listing spam)")
    state = load_state()
    notifier = DiscordNotifier(os.getenv("DISCORD_WEBHOOK_URL"),
                               dry_run=args.dry_run, cooldown_sec=cooldown,
                               cooldowns=state.get("_cooldowns"))
    if notifier.dry_run:
        print("[init] dry-run mode: alerts print to console, nothing is posted")

    if args.discover:
        discover(args.discover, notifier)
        return

    products = load_products()
    print(f"[init] tracking {len(products)} products")
    scrapers = {name: cls(pool) for name, cls in SCRAPERS.items()}

    def run_pass() -> None:
        for product in products:
            if is_unverified_placeholder(product):
                # Placeholder, not a real listing (e.g. the costco.ca
                # homepage): fetching it every pass only grows a junk fail
                # streak and burns a request against a page that can never
                # parse. It becomes tracked the moment someone replaces it
                # with a real URL and flips verified to true.
                print(f"[skip] unverified placeholder: {product.get('url')}")
                continue
            retailer = product.get("retailer")
            scraper = scrapers.get(retailer)
            if scraper is None:
                print(f"[skip] no scraper for retailer={retailer!r}")
                continue
            result = check_one(scraper, product)
            handle_result(result, state, notifier, baseline)
            time.sleep(random.uniform(1.0, 3.0))  # politeness jitter between products
        state["_cooldowns"] = notifier.cooldowns  # persist across --once restarts
        n_pruned = prune_stale_fail_streaks(state, {p.get("url") for p in products})
        if n_pruned:
            print(f"[pass] pruned {n_pruned} stale fail-streak "
                  f"{'entry' if n_pruned == 1 else 'entries'} (no longer tracked)")
        n_dropped = drop_placeholder_streaks(state, products)
        if n_dropped:
            print(f"[pass] dropped {n_dropped} placeholder fail-streak "
                  f"{'entry' if n_dropped == 1 else 'entries'} (unverified product)")
        save_state(state)
        n_urls = sum(1 for k in state if not k.startswith("_"))
        print(f"[pass] done — state saved ({n_urls} urls tracked)")

    if args.once:
        run_pass()
        return
    while True:
        run_pass()
        time.sleep(poll_interval + random.uniform(0, poll_interval * 0.25))


if __name__ == "__main__":
    main()
