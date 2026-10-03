"""Discord webhook alerts: rich embeds, per-product cooldown, dry-run mode."""
import json
import time
from datetime import datetime, timezone
from pathlib import Path
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
    def __init__(self, webhook_url=None, dry_run: bool = False, cooldown_sec: int = 1800,
                 log_path=None):
        self.webhook_url = (webhook_url or "").strip() or None
        # No webhook configured => dry-run automatically.
        self.dry_run = dry_run or not self.webhook_url
        self.cooldown_sec = cooldown_sec
        self._last_alert: Dict[Tuple[str, str], float] = {}
        # Persistent audit log of every alert attempt (project root by default).
        self.log_path = Path(log_path) if log_path else (
            Path(__file__).resolve().parent.parent / "alerts.log")

    def _log_alert(self, event_type: str, result, outcome: str) -> None:
        """Append one JSON line to the alert audit log. Never raises."""
        try:
            entry = {
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "event": event_type,
                "retailer": result.retailer,
                "name": result.name,
                "price": result.price,
                "url": result.url,
                "outcome": outcome,
            }
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except OSError:
            pass  # logging must never break alerting

    def _cooldown_ok(self, url: str, event: str) -> bool:
        key = (url, event)
        now = time.time()
        if now - self._last_alert.get(key, 0) < self.cooldown_sec:
            return False
        self._last_alert[key] = now
        return True

    def _post_with_retry(self, payload: dict) -> tuple:
        """POST the payload, retrying transient failures.

        Up to 3 attempts with exponential backoff (1s, 2s) on network errors
        and 5xx responses. 4xx responses fail fast — a 404/401 means the
        webhook URL is wrong or deleted, and retrying won't help.
        Returns (True, "") on success, (False, reason) on failure.
        """
        last_err = "unknown error"
        for attempt in range(3):
            try:
                resp = requests.post(self.webhook_url, json=payload, timeout=15)
            except requests.RequestException as exc:
                last_err = f"network error: {exc}"
            else:
                if 200 <= resp.status_code < 300:
                    return True, ""
                if 400 <= resp.status_code < 500:
                    return False, (
                        f"Discord rejected the webhook (HTTP {resp.status_code}) — "
                        "the webhook URL is probably wrong or the webhook was "
                        "deleted in Discord's server settings."
                    )
                last_err = f"HTTP {resp.status_code} from Discord"
            if attempt < 2:
                time.sleep(2 ** attempt)
        return False, f"Discord POST failed after 3 attempts ({last_err})"

    def send(self, event_type: str, result, extra: str = "") -> bool:
        """Build and deliver (or print) the embed. Returns True if sent/printed."""
        if event_type not in COLORS:
            raise ValueError(f"unknown event_type: {event_type!r}")
        if not self._cooldown_ok(result.url, event_type):
            print(f"[cooldown] suppressed {event_type} for {result.url}")
            self._log_alert(event_type, result, "cooldown-suppressed")
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
            self._log_alert(event_type, result, "dry-run")
            return True
        ok, reason = self._post_with_retry(payload)
        if not ok:
            print(f"[notifier] {reason}")
            self._log_alert(event_type, result, f"failed: {reason}")
            return False
        print(f"[alert] {event_type} -> Discord: {result.name}")
        self._log_alert(event_type, result, "sent")
        return True
