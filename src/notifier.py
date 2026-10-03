"""Discord webhook alerts: rich embeds, per-product cooldown, dry-run mode."""
import time
from datetime import datetime, timezone
from typing import Dict, Tuple

import requests

COLORS = {
    "restock": 0x2ECC71,       # green
    "out_of_stock": 0xE74C3C,  # red
    "price_drop": 0x3498DB,    # blue
    "new_listing": 0xF1C40F,   # yellow
}
TITLES = {
    "restock": "🟢 RESTOCK",
    "out_of_stock": "🔴 OUT OF STOCK",
    "price_drop": "🔵 PRICE DROP",
    "new_listing": "🟡 NEW LISTING",
}

_STATUS_LABEL = {True: "In Stock ✅", False: "Out of Stock ❌", None: "Unknown ❓"}


class DiscordNotifier:
    def __init__(self, webhook_url=None, dry_run: bool = False, cooldown_sec: int = 1800):
        self.webhook_url = (webhook_url or "").strip() or None
        # No webhook configured => dry-run automatically.
        self.dry_run = dry_run or not self.webhook_url
        self.cooldown_sec = cooldown_sec
        self._last_alert: Dict[Tuple[str, str], float] = {}

    def _cooldown_ok(self, url: str, event: str) -> bool:
        key = (url, event)
        now = time.time()
        if now - self._last_alert.get(key, 0) < self.cooldown_sec:
            return False
        self._last_alert[key] = now
        return True

    def send(self, event_type: str, result, extra: str = "") -> bool:
        """Build and deliver (or print) the embed. Returns True if sent/printed."""
        if event_type not in COLORS:
            raise ValueError(f"unknown event_type: {event_type!r}")
        if not self._cooldown_ok(result.url, event_type):
            print(f"[cooldown] suppressed {event_type} for {result.url}")
            return False
        fields = [
            {"name": "Status", "value": _STATUS_LABEL[result.in_stock], "inline": True},
            {"name": "Price", "value": result.price or "n/a", "inline": True},
            {"name": "SKU", "value": result.sku or "n/a", "inline": True},
            {"name": "Retailer", "value": result.retailer, "inline": True},
        ]
        if extra:
            fields.append({"name": "Note", "value": extra, "inline": False})
        embed = {
            "title": f"{TITLES[event_type]} — {result.name}",
            "url": result.url,
            "color": COLORS[event_type],
            "fields": fields,
            "footer": {
                "text": datetime.now(timezone.utc).strftime("Checked %Y-%m-%d %H:%M UTC")
            },
        }
        if result.image_url:
            embed["thumbnail"] = {"url": result.image_url}
        payload = {"embeds": [embed]}
        if self.dry_run:
            print(f"[dry-run] {event_type.upper():<12} {result.retailer:<14} | {result.name} | "
                  f"stock={result.in_stock} price={result.price} sku={result.sku}")
            return True
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=15)
            resp.raise_for_status()
        except Exception as exc:
            print(f"[notifier] Discord POST failed: {exc}")
            return False
        print(f"[alert] {event_type} -> Discord: {result.name}")
        return True
