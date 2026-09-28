# Maintenance runbook

## Module map

| File | Responsibility |
| --- | --- |
| build.py | CLI arguments and exit code |
| sources.json | Stable feed IDs, display names, emoji, adapter kind and URL |
| rss_service/http.py | User-Agent, timeout and bounded retry policy |
| rss_service/parsers.py | Pure HTML/RSS parsing and validation |
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
with UTC offset, or None before merging), and summary (plain text). Merge assigns
an absent date once and preserves it on subsequent runs. The renderer adds the
emoji. Never store a prefixed title in state or prefixes will accumulate.

Each source record holds items, last_attempt, last_success, last_new and error.
Status adds id, name, emoji, count and available but omits article contents.
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

Partial omissions and silent upstream ignoring of recommendation filters cannot
always be detected automatically. Inspect real output when repairing an adapter.

### Official RSS specifics

Google News Korea and Autocrypt Labs use RSS 2.0 channel/item, not Atom.
Required fields: nonempty title and HTTP(S) link. pubDate is optional; summaries
are reduced to plain text. A switch to Atom requires an explicit parser and tests.
Full article extraction is intentionally out of scope.

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
