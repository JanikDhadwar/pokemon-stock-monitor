#!/usr/bin/env python3
"""Interactive setup wizard for the Pokémon TCG Stock Monitor.

Walks you through setup in plain language:
  1. Your Discord webhook URL (validated with a real test message)
  2. Optional proxies (help beat IP blocks on Pokémon Center / Walmart)
  3. How often to check prices

Then writes your .env file and tells you exactly what to run next.

Run it with:
    .venv/bin/python setup.py          (Mac / Linux)
    .venv\\Scripts\\python setup.py      (Windows)
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.models import ProductResult
from src.notifier import DiscordNotifier

ENV_PATH = ROOT / ".env"

WEBHOOK_RE = re.compile(
    r"^https://discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_\-]+/?$"
)
PROXY_RE = re.compile(r"^https?://[^:@/\s]+:[^@/\s]+@[^:/\s]+:\d+/?$")


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        answer = ""
    return answer or default


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        answer = ask(f"{prompt} ({hint})", "").lower()
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("  Please answer yes or no.")


def step_webhook() -> str:
    print("\n── Step 1 of 3: Discord alerts ──")
    print("The monitor sends alerts to a Discord channel through a 'webhook'.")
    print("To make one (takes 30 seconds):")
    print("  1. In Discord, right-click your server → Server Settings")
    print("  2. Go to Integrations → Webhooks → New Webhook")
    print("  3. Pick the channel for alerts, then click 'Copy Webhook URL'\n")

    while True:
        url = ask("Paste your webhook URL here")
        if url.lower() in ("q", "quit", "exit"):
            cancel()
        if not WEBHOOK_RE.match(url):
            print("  That doesn't look like a Discord webhook URL.")
            print("  It should look like: https://discord.com/api/webhooks/123.../abc...")
            continue
        print("\n  Sending a test message to your Discord — check the channel now...")
        notifier = DiscordNotifier(webhook_url=url)
        result = ProductResult(
            retailer="setup",
            name="Setup test",
            url="https://github.com/",
            sku="—",
            in_stock=True,
            price="—",
        )
        if not notifier.send("new_listing", result,
                             extra="If you can see this, your alerts are working."):
            print("\n  The test message failed to send. Common causes:")
            print("  • The URL was copied incompletely (it is very long)")
            print("  • The webhook was deleted in Discord's settings")
            print("  • No internet connection right now")
            if ask_yes_no("Try a different URL", default=True):
                continue
            cancel()
        if ask_yes_no("Did the test message show up in your Discord", default=True):
            return url
        print("  Hmm — the message sent, but you can't see it. Check that you")
        print("  picked the right channel for the webhook in Discord's settings.")
        if not ask_yes_no("Try again with a different URL", default=True):
            cancel()


def step_proxies() -> str:
    print("\n── Step 2 of 3: Proxies (optional) ──")
    print("Why: Pokémon Center and Walmart block automated checkers by IP address.")
    print("Routing checks through proxies gets around that. Skip this if you")
    print("only care about Costco/Amazon, which usually work without proxies.\n")
    print("Paste one proxy per line, like:  http://user:pass@1.2.3.4:8080")
    print("When you're done, press Enter on an empty line. Or just press")
    print("Enter now to skip proxies entirely.\n")

    proxies = []
    while True:
        line = ask(f"Proxy #{len(proxies) + 1} (empty line = done)")
        if not line:
            break
        if not PROXY_RE.match(line):
            print("  That doesn't match the expected format.")
            print("  Expected: http://username:password@host:port")
            continue
        proxies.append(line.rstrip("/"))
    if proxies:
        print(f"  Got {len(proxies)} proxie(s). They'll be rotated automatically.")
    else:
        print("  No proxies — checks will go out directly from your connection.")
    return ",".join(proxies)


def step_interval() -> int:
    print("\n── Step 3 of 3: Check interval ──")
    print("How often should each product be checked?")
    while True:
        raw = ask("Minutes between checks", default="1")
        try:
            minutes = float(raw)
        except ValueError:
            print("  Please enter a number, e.g. 1 or 5.")
            continue
        if minutes <= 0:
            print("  Needs to be more than 0.")
            continue
        seconds = int(round(minutes * 60))
        if seconds < 30:
            print("  Heads-up: checking faster than ~30 seconds can get your IP")
            print("  banned by retailers. 1 minute is the safe default.")
            if not ask_yes_no("Keep it anyway", default=False):
                continue
        return seconds


def cancel() -> None:
    print("\nSetup cancelled — nothing was changed.")
    raise SystemExit(1)


def main() -> None:
    print("=" * 60)
    print("  PokéStock setup — Pokémon TCG stock alerts for Discord")
    print("=" * 60)
    print("This takes about 2 minutes. You can press Ctrl+C anytime to quit.")

    webhook_url = step_webhook()
    proxies = step_proxies()
    poll_seconds = step_interval()

    if ENV_PATH.exists():
        print(f"\nA .env file already exists at {ENV_PATH}.")
        if not ask_yes_no("Overwrite it with these new settings", default=False):
            cancel()

    ENV_PATH.write_text(
        f"DISCORD_WEBHOOK_URL={webhook_url}\n"
        f"PROXIES={proxies}\n"
        f"POLL_INTERVAL_SEC={poll_seconds}\n",
        encoding="utf-8",
    )

    print("\n" + "=" * 60)
    print("  Done! Your settings are saved.")
    print("=" * 60)
    print(f"  Webhook:   {webhook_url[:42]}... (full URL in .env)")
    print(f"  Proxies:   {len(proxies.split(',')) if proxies else 0} configured")
    print(f"  Interval:  every {poll_seconds} seconds")
    print("\nNext — add the products you hunt in config/products.yaml, then run:")
    print()
    print("    .venv/bin/python -m src.monitor --once --dry-run   # test pass, no alerts sent")
    print("    .venv/bin/python -m src.monitor                    # start live monitoring")
    print()
    print("On Windows, replace '.venv/bin/python' with '.venv\\Scripts\\python'.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        cancel()
