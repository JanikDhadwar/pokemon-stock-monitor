# Pokémon TCG Stock Monitor

Fast stock monitoring for Pokémon TCG products with **Discord webhook alerts**.
v1 scope: monitoring + alerts. **No auto-checkout.**

Tracks products across **Pokémon Center, Walmart, Costco, and Amazon** —
including the Canadian storefronts (**walmart.ca, costco.ca, amazon.ca**,
prices in CAD) — polls them on a schedule, and fires rich Discord embeds on:

- 🟢 **Restock** (out-of-stock → in-stock)
- 🔴 **Out of stock** (in-stock → out-of-stock)
- 🔵 **Price drop**
- 🟡 **New listing** (a tracked URL seen for the first time)

## Quickstart

```bash
cd pokemon-stock-monitor
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env
# edit .env -> paste your Discord webhook URL, optional proxies
nano config/products.yaml   # add the SKUs/URLs you hunt
.venv/bin/python -m src.monitor --once --dry-run   # single pass, prints alerts
.venv/bin/python -m src.monitor                    # live loop
```

## Discord webhook setup

1. Discord → your server → **Server Settings → Integrations → Webhooks**
2. **New Webhook** → pick the channel → **Copy Webhook URL**
3. Paste it as `DISCORD_WEBHOOK_URL` in `.env`

No URL (or `--dry-run`) = alerts print to the console instead of posting.
Per-product cooldown (`ALERT_COOLDOWN_SEC`, default 30 min) prevents spam.

## Proxies

Optional but recommended — retailers rate-limit/ban datacenter IPs fast.

```bash
# .env — comma-separated, or a single rotating endpoint from your provider
PROXIES=http://user:pass@proxy1:8080,http://user:pass@proxy2:8080
```

Free starting point: Webshare's free tier (10 proxies, no credit card).
Requests rotate round-robin per request. No proxies configured = direct
connection (fine for Pokémon Center, usually blocked elsewhere — see
Limitations).

## products.yaml

```yaml
products:
  - retailer: pokemoncenter   # pokemoncenter | walmart | costco | amazon
                              # walmart_ca | costco_ca | amazon_ca (Canada, CAD)
    name: "Pokémon TCG: 30th Celebration Pokémon Center Elite Trainer Box"
    url: "https://www.pokemoncenter.com/..."
    sku: "10-10447-111"       # optional; auto-detected from URL when omitted
    verified: true            # false = placeholder URL, replace me
```

## Running

```bash
.venv/bin/python -m src.monitor --once --dry-run   # single pass, no posting
.venv/bin/python -m src.monitor --once             # single pass, live alerts
.venv/bin/python -m src.monitor                    # poll loop (POLL_INTERVAL_SEC + jitter)
.venv/bin/python -m src.monitor --discover "elite trainer box"
        # scan pokemoncenter.com search for listings not in products.yaml
.venv/bin/python tests/test_smoke.py               # live smoke test, one product per retailer
```

State lives in `state.json` (created on first run). The first pass records a
**silent baseline** — no "new listing" spam for products already in the file.
Delete `state.json` to re-baseline.

## How it works

- `src/scrapers/` — one scraper per retailer, all parsing `application/ld+json`
  `Product.offers` (schema.org `InStock`/`OutOfStock`) where available.
  One retailer's failure never kills the loop — it's recorded as `error` and
  the monitor moves on.
- `src/notifier.py` — Discord embeds with SKU/price/status/link/thumbnail.
- `src/monitor.py` — poll loop, `state.json` diffing, event detection.

## Limitations (read this)

- **All retailers run bot protection** (US and Canadian storefronts alike).
  In testing from a datacenter IP with no proxies: Pokémon Center
  hard-blocked with **HTTP 403 from CloudFront**, Walmart (.com and .ca)
  served **PerimeterX challenge pages**, Amazon (.com and .ca) surprisingly
  served real pages (your mileage will vary — CAPTCHAs are the norm), and
  **Costco (.com) worked cleanly** with real `ld+json` stock data.
  Residential/rotating proxies are the realistic fix for the blocked ones;
  see TEST_RESULTS.md for the full per-retailer breakdown.
- When a retailer blocks us the monitor reports `in_stock=None` with an
  explanatory error instead of guessing. Unknowns never overwrite
  last-known-good state and never fire alerts.
- Polling faster than ~30s/product/retailer gets you banned faster. The
  default 60s + jitter is a sane starting point.
- This is **not** "as good as the paid monitors" out of the box — those run
  residential proxy fleets and retailer APIs. This gets you ~80% of the way
  for $0.

## Layout

```
├── config/products.yaml   tracked products
├── src/
│   ├── models.py          ProductResult, StockStatus
│   ├── proxies.py         ProxyPool (round-robin)
│   ├── notifier.py        Discord embeds + cooldown + dry-run
│   ├── monitor.py         CLI poll loop + --discover
│   └── scrapers/          base.py + one module per retailer
├── tests/test_smoke.py    live one-per-retailer smoke test
├── TEST_RESULTS.md        honest per-retailer test notes
└── state.json             last-known stock/price (auto-created)
```
