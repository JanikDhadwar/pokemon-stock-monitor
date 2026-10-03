# Test Results — 2026-10-02

**Environment:** datacenter IP, **zero proxies**, 20s timeout, 2 retries.
`python -m src.monitor --once --dry-run` (8 products) + `tests/test_smoke.py`
+ synthetic transition test + `--discover`. No results faked.

## Per-retailer results

| Retailer | Result | Detail |
|---|---|---|
| Pokémon Center (2 products) | ❌ **Blocked** | HTTP **403 from CloudFront** on every attempt — product pages *and* search pages. Hard IP block, not parseable. The `ld+json` parse logic matches Pokémon Center's confirmed JSON-LD structure (verified via search-engine cache of product pages), but it has **never successfully run live**. Residential proxies are required before this retailer works at all. |
| Walmart (2 products) | ❌ **Blocked** | **PerimeterX challenge page** served for both product URLs. The `__NEXT_DATA__` parser + `ld+json` fallback are written but **untested against a real page** — they may need fixes once traffic goes through clean IPs. |
| Costco (2 products) | ✅ **Works** | Real pages (HTTP 200, correct `<title>`), real `ld+json`: both 5-pack mini tins parse as **OutOfStock / $39.99**. Manually verified the raw JSON-LD. This retailer genuinely works from a datacenter IP today. |
| Amazon (2 products) | ✅ **Works (for now)** | Real pages (HTTP 200, correct titles), **no CAPTCHA this run**. Stock via `#availability` span fallback, price via embedded `displayPrice` JSON: GO ETB **InStock / $199.67**, Paldean Fates ETB **InStock / $537.99** (third-party seller pricing — insane but that's what the page says). ⚠️ Amazon CAPTCHAs datacenter IPs routinely; treat this as lucky, not reliable. |

## Pipeline tests

- **Monitor loop** (`--once --dry-run`, 8 products): completes cleanly; per-product
  failures are isolated (PC/Walmart errors never touched Costco/Amazon results).
- **Baseline behavior**: first run with no `state.json` records silently — zero
  alert spam. Verified.
- **Transition detection** (synthetic): flipped a Costco product to
  `in_stock=True, price=49.99` in `state.json`, re-ran — correctly fired
  **OUT_OF_STOCK** and **PRICE_DROP** dry-run embeds with right SKU/price/link.
  State restored afterwards.
- **Cooldown**: second identical event within 30 min prints `[cooldown] suppressed`
  instead of re-alerting. Verified in code path (notifier unit behavior).
- **`--discover "elite trainer box"`**: fails gracefully — both search URL
  variants 403 (same CloudFront wall), prints a clear message, exits 0.
- **Smoke test** (`tests/test_smoke.py`): exit 0, prints honest per-retailer
  table (see above). Never fails the suite on retailer blocks by design.

## Honest bottom line

- **2 of 4 retailers work right now with $0 infra** (Costco fully, Amazon
  intermittently). The parse code is real and verified where pages were
  reachable.
- **Pokémon Center — the most important retailer for this use case — is
  completely blocked** from datacenter IPs. The #1 upgrade that matters is
  residential/rotating proxies, not more code.
- **Walmart's parsers are untested** against real pages; expect a debugging
  round once clean IPs are in play.
- This is **not** "as good as the paid monitors." Paid services win on proxy
  fleets and retailer APIs, not parser cleverness. What this *is*: a correct,
  honest v1 foundation — clean architecture, graceful failure, real Discord
  embeds — that gets meaningfully better the moment proxies are added.

## Canadian retailers — 2026-10-02

Environment: datacenter IP, zero proxies, same as above. New retailer keys
`walmart_ca`, `costco_ca`, `amazon_ca` are thin subclasses of the US scrapers
(page structures near-identical); prices pass through in CAD, no conversion.

| Retailer | Result | Detail |
|---|---|---|
| walmart.ca (2 products, verified URLs) | ❌ **Blocked** | PerimeterX bot-challenge page, same as walmart.com. `__NEXT_DATA__` parser untested against a real page. Needs residential proxies. |
| amazon.ca (2 products, verified URLs) | ⚠️ **Reachable, no stock signal** | HTTP 200, correct title, **no CAPTCHA** — but the buybox/availability is client-side rendered (spinner div, no `#availability` text, no `displayPrice` JSON, zero ld+json blocks). Scraper correctly reports unknown instead of guessing. A headless browser (or Amazon's offer API) is the realistic fix. |
| costco.ca (placeholder URL) | ❌ **Untestable** | No verified costco.ca Pokémon product URL found via web search; seeded as `verified: false` placeholder. Homepage fetch hit the Akamai bot wall. Replace the placeholder with a real `/p/` product URL and re-test. |

Bottom line: the CA scaffolding is correct and follows the same graceful-failure
pattern — nothing guesses. walmart.ca needs proxies like its US sibling,
amazon.ca needs JS rendering for the buybox, costco.ca needs a real product
URL first.
