# Test fixtures

Synthetic minimal HTML pages used by `tests/test_parsers.py`. No network is
touched — each fixture exercises one parser code path.

- `pokemoncenter_*.html` — mirror the schema.org `Product` ld+json structure
  the parser was written against (confirmed from Pokémon Center's documented
  page structure; the parser has not run against a live page because
  pokemoncenter.com hard-blocks datacenter IPs — see TEST_RESULTS.md).
- `walmart_*.html` — mirror the embedded `__NEXT_DATA__` JSON shape and the
  PerimeterX challenge page (`px-captcha`). The `walmart_ldjson_fallback.html`
  fixture covers the ld+json fallback when `__NEXT_DATA__` is absent.
- `costco_*.html` — mirror the ld+json shape observed on **live** costco.com
  product pages during testing (OutOfStock / $39.99 on the mini tins).
- `amazon_*.html` — mirror the `#availability` span + embedded `displayPrice`
  JSON observed on **live** amazon.com pages, plus the ld+json path and the
  "Enter the characters you see below" CAPTCHA page.

Bot-wall fixtures: `*_botwall.html` files are served to the scraper with the
HTTP status the real wall uses (403 for Pokémon Center/PerimeterX-style,
403 for Costco/Akamai). The Amazon CAPTCHA fixture is served as HTTP 200
because Amazon serves the challenge page with a 200 status.
