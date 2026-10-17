# Maintenance runbook

## Module map

| File | Responsibility |
| --- | --- |
| build.py | CLI arguments and exit code |
| sources.json | Stable feed IDs, display names, emoji, adapter kind and URL |
| rss_service/http.py | List requests and separately bounded, non-redirecting article requests |
| rss_service/article.py | Opt-in DC body queue, rate limits and persistent attempt state |
| rss_service/parsers.py | Pure HTML/RSS parsing and validation |
| rss_service/images.py | Narrow DC image-host normalization and escaped Miniflux rule generation |
| integrations/miniflux-dcinside.json | Shared supported scraper/rewrite settings for the five DC subscriptions |
| rss_service/collection.py | Adapter selection and DC pagination |
| rss_service/state.py | Deduplication, stable fallback dates, 1,000-item retention |
| rss_service/rendering.py | RSS serialization and static status page |
| rss_service/pipeline.py | Restore state, isolate failures, write all artifacts |
| .github/workflows/feeds.yml | Schedule, durable state, deployment, failure signal |
| tests/test_build.py | Offline regression tests |

The output directory contains feeds/*.xml, state.json, status.json, index.html,
subscriptions.opml and .nojekyll. Actions restores it from the data branch, then
commits it back before Pages deployment. Local output is ignored by git. Treat
state.json as durable production data, not a disposable cache.

## Data contracts

An item has id (canonical URL/GUID), title (without emoji), link, date (ISO 8601
with UTC offset, or None before merging), and summary (plain text). Enriched DC items also carry `content_html`,
`content_status` (`pending`, `ready`, `image_only`, `failed`), `content_image_count`,
`content_attempts`, `content_checked_at`, `content_retry_at` (after HTTP 429) and
`content_error`. Body timestamps use UTC offsets. `ready` means HTML is available,
not that images were downloaded or their content understood. Merge preserves body
fields and their text excerpt when a later list page repeats the same item.
Merge assigns
an absent date once and preserves it on subsequent runs. The renderer adds the
emoji. Never store a prefixed title in state or prefixes will accumulate.

Each source record holds items, last_attempt, last_success, last_new and error.
State and status also persist `consecutive_failures`, `first_failure` and
`alert_required`. Temporary collection transport failures (connection errors,
timeouts, HTTP 429/5xx) require both three consecutive failed runs and three hours
since last success to fail Actions. Without prior success, use first_failure.
A successful collection resets that source's streak. Parser/validation,
pagination warnings, rendering and infrastructure failures remain immediate. Deferred errors remain visible in status
and logs; repeated alerts after the threshold are not deduplicated.
Status adds id, name, emoji, retained count, published_count and available but omits article contents.
Enabled body collectors also retain `body_collection` counts (`ready`, `pending`,
`failed`, `attempted`). These counts advance only after RSS replacement succeeds;
body errors are visible separately from feed-list/render errors.
A successful fetch with no newly discovered IDs advances last_success only.
Pagination-cap warnings publish partial results and advance last_success, but
set error and fail the workflow because completeness is uncertain.

RSS files are replaced atomically, and success metadata advances only after the
write succeeds. Other build artifacts are written at the end. A global failure
such as corrupt state or disk exhaustion may prevent status deployment; inspect
Actions rather than trusting an older Healthy snapshot.

## Diagnose before changing selectors

1. Check Actions logs and the timestamp/error in the public status.json.
2. Separate HTTP failures, empty bodies, block pages, markup changes, XML errors
   and workflow/Pages permission failures. HTTP 200 alone is not success.
3. Download a response using the headers in http.py. DC may return an empty body
   without the browser User-Agent. A local success does not prove runner access.
4. Save a minimal sanitized reproduction, then add a failing offline test.
5. Update only the affected adapter; rerun tests and a bounded live collection.
6. Inspect title, board ID, recommendation filter, date timezone, GUID stability,
   notice exclusion and pagination before pushing.

Do not bypass access controls or remove validation to mask upstream blocking.

### DCInside specifics

Rows: tr.ub-content.us-post; numeric data-no is the article number.
Notice signals: data-type containing notice, or .gall_subject notice/survey/AD.
Title: first .gall_tit anchor whose href contains /board/view/ (not reply link).
Date: .gall_date title attribute, parsed in Asia/Seoul's fixed UTC+09 offset.
Canonical URL retains only id and no. Standard and mgallery paths differ.
Pagination preserves the supplied query, including exception_mode=recommend,
and adds page and list_num=100. First run reads only one page. Subsequent runs
stop at a known article, reject repeated pages and warn at ten pages.

Body collection is enabled for all five DC feeds through `article_content`.
Google News and Autocrypt Labs are excluded.
The parser accepts exactly one `.write_div` container; an image-only post is valid.
It strips active markup/attributes, normalizes ordinary HTTP(S) links, resolves lazy
image URLs and serializes sanitized HTML into the RSS content namespace. No image
fetches occur during publishing. A reader may still be unable to fetch a remote
image; never report rendered-image/OCR success from HTML extraction alone.

For `viewimage.php` and `dccon.php` only, known `dcimgN` hosts on `dcinside.co.kr`
and `dcinside.com` become `https://image.dcinside.com`; raw queries remain intact.
`viewimagePop.php`, other hosts/routes and non-image links are left alone. Existing
cached bodies get the same adjustment at render time for enabled DC feeds, with
no image downloads, body refetches or mutation of the cached record.
See [Miniflux integration](miniflux.md) for Download rules and their required
string-decoding/regex validation before applying to a live subscription.

Only new IDs receive body queue state. Existing metadata-only IDs are not bulk
backfilled. Pending state survives pagination and later runs. Ten requests per
feed/run, two-second pacing, three attempts and hourly minimum retry spacing are
constants in `article.py`. 401/403/404/410 stop retries for that item. 429 stops body
work for the feed and persists cooldown, including longer `Retry-After` values.
Article responses are limited to 1 MiB with 5-second connection and 10-second read
inactivity timeouts. A 20-second budget is checked between response chunks; it is
not a hard wall-clock deadline. The workflow also has a 25-minute job timeout.
Article requests accept only canonical DC view URLs and do not follow redirects.

Pending/failed DC bodies remain in state with their original GUID/date; do not
emit placeholder RSS articles. Publish only once content_html is available, including
image-only bodies. A failed item remains in the body status counts; do not erase it
or fail the whole list collection. Old metadata-only items without content_status
are preserved, not bulk backfilled. Do not repeatedly reset
failed attempt counters to get around access restrictions. Disabling the flag leaves
existing content intact. The five enabled feeds have an aggregate ceiling of fifty
article requests per run, processed sequentially. Ten requests and HTTP 429
cooldown remain per-feed, not a shared cross-feed rate limiter. Before expanding
further or increasing the budget, review host load and test the target reader.

Partial omissions and silent upstream ignoring of recommendation filters cannot
always be detected automatically. Inspect real output when repairing an adapter.

### Official RSS specifics

Google News Korea and Autocrypt Labs use RSS 2.0 channel/item, not Atom.
Required fields: nonempty title and HTTP(S) link. pubDate is optional; summaries
are reduced to plain text. A switch to Atom requires an explicit parser and tests.
Full article extraction for these official RSS sources is not enabled.

## Validation commands

```sh
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/black --check build.py rss_service tests
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python build.py --output /tmp/rss-check
# Repeat with the same output to exercise saved history and pagination.
.venv/bin/python build.py --output /tmp/rss-check

gh run list --limit 5
gh run view RUN_ID --log-failed
```

For a bounded body smoke test, use `fetch_article`, `parse_dc_article` and
`write_feed` on one or two public posts in a temporary directory. Do not run the
full collector merely to check a selector: it can enqueue many new articles.
Verify content namespace parsing, image links, absence of handlers/scripts,
unchanged GUID/title/date, and no second body request when saved state is reused.
Local success does not verify GitHub runner access or Miniflux/Capy image rendering.

Tests must remain network-free. Include failure isolation, last-good preservation,
empty/blocked responses, canonical IDs, recommendation filters and date handling.
Do not deliberately fail production just to test email without user permission.

## Release and recovery

- Push main only after tests; this triggers collection and Pages deployment.
- Verify the run completes, then check public status.json and parse all seven XMLs.
- If needed, fix forward or revert the offending code commit; retain data history.
- Use workflow_dispatch for another run. A data-only push does not trigger main's
  workflow. The concurrency group serializes scheduled/manual/push builds.
- Preserve Contents write, Pages write, OIDC permissions and Pages workflow mode.
- GitHub's scheduled runs can be late/skipped; no external heartbeat was requested.
- Email notifications depend on the user's Actions email/failed-only preferences.
- Public data and logs must never contain secrets or the personal OPML export.

## Adding a source

Choose a permanent URL-safe ID; add its URL, kind, name and emoji to sources.json.
For an existing adapter, add configuration coverage. For a new adapter, add pure
parsing tests and route it explicitly in collection.py. Keep output item contracts.
Update README and the static page's source count (currently seven). First verify
in a temporary output directory, then deploy and import the new feed into Feedly.
Do not assume adding to this repository subscribes the user's Feedly account.
