# PokéStock — Pokémon TCG Stock Alerts for Discord

PokéStock watches Pokémon trading card product pages and pings your Discord
the moment something **restocks**, **drops in price**, or a **new listing**
appears. No auto-buying — it alerts you, and you check out yourself.

It tracks products across **Pokémon Center, Walmart, Costco, and Amazon**,
including the Canadian stores (**walmart.ca, costco.ca, amazon.ca** — prices
in CAD).

## What you need

- A computer that can stay on (Windows, Mac, or Linux)
- **Python 3.10 or newer** — free from
  [python.org](https://www.python.org/downloads/).
  On Windows, tick **"Add python.exe to PATH"** during install.
- A **Discord server** where you can create webhooks (your own server works).
- About 10 minutes.
- Optional: free proxies (explained below) for Pokémon Center and Walmart.

## Setup, step by step

**1. Get the project.**
On GitHub, click **Code → Download ZIP** and unzip it somewhere — or, if you
have git:
```bash
git clone https://github.com/JanikDhadwar/pokemon-stock-monitor.git
```

**2. Open a terminal in the project folder.**
- Windows: right-click the folder → "Open in Terminal"
- Mac: right-click the folder → "New Terminal at Folder"

**3. Install the pieces it needs.**
Mac / Linux:
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```
Windows:
```bash
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

**4. Run the setup wizard.**
Mac / Linux:
```bash
.venv/bin/python setup.py
```
Windows:
```bash
.venv\Scripts\python setup.py
```
It asks three things, in plain English:
1. **Your Discord webhook URL** — it shows you exactly where to find it
   (Server Settings → Integrations → Webhooks → New Webhook → Copy URL),
   then sends a real test message so you confirm it works before continuing.
2. **Proxies (optional)** — one line explains why; paste them or skip.
3. **How often to check** — default is every 1 minute.

Everything is saved to a `.env` file on your computer. Your webhook URL and
proxy passwords stay local — they are never uploaded anywhere.

**5. Add the products you hunt.**
Open `config/products.yaml` in any text editor and add entries like this:

```yaml
products:
  - retailer: pokemoncenter   # pokemoncenter | walmart | costco | amazon
                              # walmart_ca | costco_ca | amazon_ca (Canada, CAD)
    name: "Pokémon TCG: Mega Evolution—Delta Reign Elite Trainer Box"
    url: "https://www.pokemoncenter.com/product/10-10438-112/..."
    sku: "10-10438-112"       # optional — usually detected from the URL
```

A few example products are already in the file — keep them or delete them.

**6. Start it.**
```bash
.venv/bin/python -m src.monitor --once --dry-run   # test run: prints what it finds, sends nothing
.venv/bin/python -m src.monitor                    # live: checks on a loop, alerts to Discord
```
(Windows: use `.venv\Scripts\python` instead of `.venv/bin/python`.)

The first run is quiet on purpose — it records a baseline of current
prices and stock so you don't get spammed. Alerts start on later runs, when
something actually changes.

## What the alerts look like

Each alert is a Discord message with a colored title:

- 🟢 **RESTOCK** — was out of stock, now available
- 🔴 **OUT OF STOCK** — was available, now gone
- 🔵 **PRICE DROP** — price went down (shows old → new)
- 🟡 **NEW LISTING** — a tracked product URL seen for the first time

Every alert shows status, price, SKU / product number, retailer, a link to
the product page, and the product image when available. To avoid spam, the
same alert won't repeat for 30 minutes. Price drops also have a significance
gate: a drop only pings when it's at least $1 **and** at least 1% below the
reference price, so cent-level flickers on third-party listings stay quiet
(tune with `MIN_PRICE_DROP_ABS` / `MIN_PRICE_DROP_PCT` in `.env`). If a send
fails, it's retried automatically.

## Running it 24/7

Just leave the `python -m src.monitor` loop running on a computer that's on.
For a set-and-forget schedule instead, run a single pass on a timer:

- Mac/Linux cron — every 5 minutes:
  ```bash
  */5 * * * * cd /path/to/pokemon-stock-monitor && .venv/bin/python -m src.monitor --once
  ```
- Windows: Task Scheduler → run `.venv\Scripts\python -m src.monitor --once`
  every 5 minutes.

(`--once` does one full check and exits; the plain loop version never exits.)

## Do I need proxies?

Short version: for **Costco and Amazon**, usually not. For **Pokémon Center
and Walmart**, yes.

All four retailers run bot protection. From a normal home connection, Costco
and Amazon often work fine. Pokémon Center and Walmart are much stricter —
Pokémon Center hard-blocks many IPs outright (HTTP 403), and Walmart serves
bot-check pages. Routing your checks through proxies (different IP addresses)
gets around that.

Free starting point: Webshare's free tier gives you 10 proxies, no credit
card. Paste them into the setup wizard. One honest caveat: free proxies are
*datacenter* IPs, and Pokémon Center in particular is good at blocking those
too. Paid *residential* proxies (a few dollars a month) are the reliable fix —
that's exactly what the paid monitor services are selling you.

When a retailer blocks us, the monitor reports the product as "unknown"
instead of guessing — unknown products never trigger false alerts and never
overwrite the last good reading.

## Honest limitations

- **Pokémon Center** is the most wanted and the most blocked. Without
  proxies it returns HTTP 403 for nearly everyone; with free datacenter
  proxies it's hit-or-miss; residential proxies are the real answer.
- **Walmart** (.com and .ca) serves PerimeterX bot-check pages to most
  automated checkers. Its page parser hasn't been verified against a live
  page yet — expect a debugging round once you're on clean IPs.
- **Amazon** (.com and .ca) worked in testing, but Amazon CAPTCHAs
  aggressively and unpredictably — treat it as "usually works".
- **Costco** (.com) worked cleanly in testing with real stock data.
- Checking faster than ~30 seconds per retailer risks getting your IP
  banned. 1 minute is the safe default.
- This is not magic: paid services win with huge proxy fleets. This gets
  you most of the way there for $0 — and beats every human refreshing a page.

Full per-retailer test notes: [TEST_RESULTS.md](TEST_RESULTS.md).

## Troubleshooting

**"The test message failed to send" (setup wizard)**
- The webhook URL is very long — make sure you copied all of it.
- In Discord: Server Settings → Integrations → Webhooks — check the webhook
  still exists and points at the right channel.
- Check the computer running setup has internet access.

**"I started it but got no alerts"**
- Normal at first: run one records a silent baseline; alerts start when
  something *changes*. Delete `state.json` to re-baseline.
- If a product shows as "unknown" in the terminal output, that retailer is
  blocking you — see "Do I need proxies?" above.
- The same alert won't repeat within 30 minutes (spam protection).

**"Proxy errors" / everything shows 'request failed'**
- Check the format: `http://username:password@host:port`, one per line in
  setup (they're stored comma-separated in `.env`).
- Free proxy accounts can expire or run out of bandwidth — check your
  provider's dashboard.
- To go back to a direct connection, empty the `PROXIES=` line in `.env`.

**Wrong product info or "SKU not found"**
- Double-check the product URL opens the right page in your browser.
- The `sku:` field is optional — when omitted it's guessed from the URL.

## For the curious: how it works

- `setup.py` — the interactive setup wizard.
- `src/scrapers/` — one parser per retailer. They read the structured
  product data (`application/ld+json`) embedded in product pages. One
  retailer's failure never stops the others.
- `src/notifier.py` — builds the Discord messages, retries failed sends.
- `src/monitor.py` — the check loop; remembers last-seen prices in
  `state.json`; decides what counts as a restock, price drop, or new listing.
- `config/products.yaml` — your watch list.
- `tests/` — `test_parsers.py` runs offline unit tests against saved page
  fixtures (`pytest tests/ -q`); `test_smoke.py` does a live one-per-retailer
  check.

No auto-checkout, by design: the bot alerts, you buy.
