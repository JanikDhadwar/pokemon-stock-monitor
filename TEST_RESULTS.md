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

## Proxy attempt — 2026-10-02 ~23:20 PDT

- Webshare free account created and email-verified (`janikdhadwar23@gmail.com`);
  10 datacenter proxies active and wired into `.env` as `PROXIES`
  (gitignored — secrets are never committed).
- **Could not verify unblocking from this VM**: the runtime sandbox blocks raw
  TCP connections to third-party proxies (`other_tcp: Deny`), so every
  proxied request dies before leaving the machine. Direct (unproxied)
  requests still work — that's how Costco/Amazon tested fine earlier.
- The proxy code path itself is sound (pool loads all 10, round-robin
  rotation confirmed); the block is environmental, not a code bug.
- To actually verify Pokémon Center / Walmart unblocking: run the monitor on
  an unsandboxed machine (your own PC — see README), or set Muse Settings →
  Permissions → Direct network protocols → `other_tcp` to Ask and re-run
  the proxied test here.
- Honest expectation: these are *datacenter* proxies, and Pokémon Center's
  CloudFront wall already blocks datacenter IPs. They may or may not get
  through — residential proxies remain the reliable fix for PC specifically.

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

## Live behavior — 2026-10-06 (upkeep pass)

- **amazon.ca partial upgrade**: `amazon_ca` / `B0G3CY83L5` (Mega Evolution—
  Ascended Heroes ETB) now returns a real signal from this VM: the
  `#availability` span reads **"In Stock"** and the embedded `displayPrice`
  is **$250.00 CAD** — two corroborating signals, no CAPTCHA, zero ld+json
  blocks. The sibling product `B0GFZV1ZVV` still returns "no stock signal"
  (spinner-era behavior), so availability varies per listing. The parser did
  not hallucinate this: the page genuinely carries a buybox now.
- **Price-drop spam fix is holding**: since the 2026-10-03 persistent-cooldown
  fix, only **1 price-drop alert** has fired (Pokémon GO ETB, Oct 5) vs 12 in
  ~4.5 hours on Oct 3. Follow-up 2026-10-06: price drops now also need to be
  ≥$1 **and** ≥1% to ping, killing the remaining cent-level flicker alerts.
- **Hosted check job** (`pokestock-monitor-check`, every 5 min) is healthy:
  zero consecutive failures, latest state writes current (costco.com both
  OutOfStock/$39.99, amazon.com both InStock).

## Live behavior — 2026-10-09 (upkeep pass)

- **Duplicate-fire incident (Oct 8)**: `alerts.log` showed two identical
  price-drop alerts ($250.00, `amazon.ca` `B0G3CY83L5`) sent 72 seconds
  apart. Root cause: a stalled `--once` pass was still alive when cron
  fired the next one — both loaded the same stale `state.json`/`_cooldowns`
  at startup, so both passed the 30-min cooldown and both fired, then raced
  on saving state. The cooldown design was fine; the missing piece was a
  single-instance guard.
- **Fix**: `acquire_singleton_lock()` in `src/monitor.py` takes a
  non-blocking exclusive `fcntl.flock` on `monitor.lock` (repo root) before
  anything else; a second process exits with `[lock]` instead of
  double-alerting. Lock releases automatically on process exit, so a crash
  can never wedge the monitor. Windows falls back to no lock (no `fcntl`);
  `monitor.lock` added to `.gitignore`. New tests in
  `tests/test_singleton_lock.py` (4 tests; lock-conflict behavior verified
  against separate processes too).
- **Test suite**: 47/47 passing (43 existing + 4 new lock tests).

## Live behavior — 2026-10-12 (upkeep pass)

- **Failed-POST cooldown bug**: in `DiscordNotifier.send()`, the per-event
  cooldown stamp was set *before* the webhook POST, so a failed POST (network
  blip, Discord outage) consumed the 30-min cooldown anyway and the alert was
  silently dropped until the cooldown expired. Fix: `send()` now restores the
  previous cooldown stamp when the POST fails, so the next pass retries
  promptly. New test `test_failed_send_does_not_consume_cooldown` in
  `tests/test_notifier_log.py` (POST mocked to fail; asserts 3 retry attempts
  and a second `send()` hits the network again, not cooldown-suppressed).
- **Test suite**: 48/48 passing.

## Live behavior — 2026-10-24 (upkeep pass)

- **Amazon fully bot-walled from the VM for ~1–2 days**: all four Amazon
  listings (US ×2, CA ×2) now fail every pass (fail streaks ~290–620, i.e.
  ~24–52h). Last real reads: GO ETB US $193.12 (Oct 16 price drop),
  Perfect Order CA $120.00 (Oct 22), Ascended Heroes CA $268.68 (Oct 21),
  Paldean Fates US $528.98 (Oct 23 ~04:43 PDT). Costco US still returns real
  data (both 5-pack mini tins out of stock / $39.99). Pokémon Center/Walmart
  blocks unchanged (expected, no proxies).
- **Hosted check job** (`pokestock-monitor-check`, every 5 min) healthy:
  every run exits 0; the singleton lock correctly bounced my own dry-run
  attempt when a live pass was mid-run (no double-processing).
- **Improvement this pass (alert quality)**: the monitor previously stayed
  silent when a working retailer went dark — Janik only found out from cron
  logs. `handle_result()` now fires a one-shot Discord `retailer_outage`
  alert when a URL that previously returned real data crosses
  `OUTAGE_ALERT_STREAK` consecutive failures (default 288 = 24h at the
  hosted 5-min cadence, env-overridable). The alert names the streak length
  and the last good read (time, stock, price). Expected always-blocked
  retailers (Pokémon Center, Walmart, costco.ca placeholder) never qualify
  because they have no last-known-good data. The flag lives in
  state["_outage_alerted"], is set only after a successful send (a failed
  POST retries next pass instead of being swallowed — same philosophy as
  the Oct 12 fix), and clears on the next successful read so a future
  outage alerts again. New `tests/test_outage_alerts.py` (6 tests).
- **It fired for real on the first live run**: the 5-min hosted cron picked
  up the new code from the working tree and POSTed 3 genuine
  `retailer_outage` Discord alerts (alerts.log outcome "sent", ~00:07–00:08
  PDT): GO ETB (292 straight failures), Perfect Order CA (391), Ascended
  Heroes CA (625) — each naming its last good read. The 4th Amazon URL
  (Paldean Fates, streak ~233) will fire its own one-shot when it crosses
  288 (~24h after its last good read).
- **Test suite**: 66/66 passing (60 existing + 6 new).

## Live behavior — 2026-10-21 (upkeep pass)

- **Re-tested every retailer honestly**: `PROXIES= .venv/bin/python -m src.monitor --once --dry-run` (13 products, 7 retailers, direct connection, no proxies) from the VM sandbox. Nothing faked.
  | Retailer | Result | Detail |
  |---|---|---|
  | Pokémon Center (2) | ❌ Blocked | HTTP **403 from CloudFront** on both — unchanged since Oct 2. |
  | Walmart US (2) | ❌ Blocked | PerimeterX challenge page on both — unchanged. |
  | Walmart CA (2) | ❌ Blocked | PerimeterX challenge page on both — same wall as US. |
  | Costco US (2) | ✅ Works | Real pages, both 5-pack mini tins **OutOfStock / $39.99**. |
  | Amazon US (2) | ✅ Works | Real pages: GO ETB **InStock / $193.12**; Paldean Fates ETB **InStock / $528.98** (third-party seller pricing — was $356.99 on Oct 13, climbed back). |
  | Amazon CA (2) | ⚠️ Partial | Ascended Heroes ETB readable: **InStock / $269.38**. Perfect Order ETB returned a bot-walled page with no stock signal (fail streak 3) — same intermittent walling seen Oct 19. |
  | Costco CA (1) | ❌ Not trackable | Product entry is a placeholder ("replace with a real /p/ product URL") pointing at costco.ca/ root, which serves a bot-challenge page. Needs a real product URL in `config/products.yaml` — Janik's side to supply. |
- **Hosted check job health**: `pokestock-monitor-check` (every 5 min, `PROXIES=` forced empty per its cron body) succeeds on every run; alerts keep flowing (last in `alerts.log`: Oct 18 restock on the Perfect Order ETB, $134.80). The Oct 8 duplicate-fire cause (stale-state race between overlapping passes) is gone — during this pass my own dry-run attempt collided with a live cron pass and the singleton lock correctly made the second process exit with `[lock]` instead of double-processing.
- **Side note**: a dry-run accidentally ran with `PROXIES` picked up from `.env` (10 Webshare proxies, blocked in this sandbox) and every product UNKNOWNed; it self-corrected on the next hosted pass (fail streaks cleared on successful reads). The cron body already forces `PROXIES=` — nothing to fix.
- **Improvement this pass (parser robustness)**: Amazon serves its bot wall as HTTP **503** (the "dog page"), previously reported as a bare `HTTP 503` — indistinguishable from a real outage in cron logs and `_fail_streaks`. `AmazonScraper.check()` now names it: `bot wall (HTTP 503): CAPTCHA/bot-check page served` when the body carries bot-check markers (added Amazon's "not a robot" phrasing and the dog-page's "automated access to Amazon data" footer to `CAPTCHA_HINTS`); a 503 without markers still reports plain `HTTP 503`. CA subclass inherits the behavior (the Oct 19 amazon.ca walling was the motivator). New tests: `test_dogpage_503_named_as_botwall`, `test_plain_503_stays_plain`, `test_dogpage_503_on_amazon_ca` (+ fixture `amazon_dogpage_503.html`).
- **Test suite**: 60/60 passing (57 existing + 3 new).

## Live behavior — 2026-10-27 (upkeep pass)

- **Hosted check job** (`pokestock-monitor-check`, every 5 min) healthy:
  enabled, 0 consecutive failures, last run 00:03 PDT today succeeded.
  `state.json` fresh (Costco entries checked 07:02 UTC). `checks.log`
  looks stale (last line Oct 24) only because it is written on degraded
  runs, not every pass — the job itself is current.
- **Amazon US still dark (~4 days)**: GO ETB fail streak 1155 (last good
  Oct 23, $193.12), Paldean Fates 1096 (last good Oct 23, $528.98). Both
  outage alerts already sent Oct 24; no new action needed.
- **Amazon CA flapping, system working as designed**: Ascended Heroes CA
  recovered ~Oct 25 ($242.69) then went dark again — the outage flag had
  cleared on recovery, so the second outage alert fired correctly on
  Oct 26 13:33 UTC at streak 288. Perfect Order CA is live again right
  now ($134.99, checked 07:03 UTC) with no alert owed (price up from its
  $120.00 alerted floor, still in stock).
- **Costco US still live**: both 5-pack mini tins OutOfStock / $39.99.
  Pokémon Center / Walmart / costco.ca placeholder blocks unchanged
  (expected, no proxies).
- **Improvement this pass (alert quality)**: the outage alert had no
  mirror — Janik heard when a retailer went dark but never when it came
  back (Perfect Order CA's quiet recovery was the case in point).
  `handle_result()` now fires a one-shot `retailer_recovered` Discord
  ping when a URL with an outstanding outage flag returns real data,
  naming the failed-check streak, when the outage was alerted, and the
  last read before the outage. The flag clears only after a successful
  send (failed POST retries next successful pass, same philosophy as
  the Oct 12 fix), and no ping fires for URLs that never had an outage
  alert. New notifier event type (`🔄 RETAILER BACK ONLINE`, teal).
  No spurious pings on deploy: the three currently-flagged URLs are all
  still failing, and Perfect Order CA's flag already cleared under the
  old code when it recovered.
- **Test suite**: 69/69 passing (66 existing + 3 new recovery tests;
  the existing recovery test updated for the extra ping).
