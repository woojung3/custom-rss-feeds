# Custom RSS Feeds

Seven hourly feeds, published as static XML on GitHub Pages:

https://woojung3.github.io/custom-rss-feeds/

Import `subscriptions.opml` from that site into Feedly, or subscribe to individual
`feeds/*.xml` URLs. Article titles have a distinct emoji per source. The original
personal Feedly export is deliberately excluded from this public repository.

## Sources

- DCInside real-time best (all ordinary posts; no notices)
- Google News Korea (official RSS; excerpts, not full article extraction)
- Autocrypt Labs (official RSS; plain-text excerpts)
- DCInside ai_utilize, thesingularity, cartoon, comic_new6 (recommended posts only)

Configuration lives in `sources.json`. Source access and markup may change.
Titles, links, dates and available excerpts are retained for all sources.
All five DC feeds publish sanitized bodies for new posts with remote image
links. Google News and Autocrypt Labs retain plain-text excerpts. Respect source policies and access restrictions.

## Schedule and state

Actions runs at minute 17 every hour (UTC and Korea both have the same minute).
Schedules can be delayed or skipped by GitHub; public repositories with no
activity for 60 days can have schedules disabled. Published state updates are
committed to the `data` branch. No external heartbeat service is configured.

On the first collection, DC feeds start with one page (up to 100 posts). Later
runs paginate up to ten pages until a previously seen article is found, sleeping
between pages. Hitting the page cap raises a visible warning and fails the run,
but publishes the collected posts. Up to 1,000 items per feed are retained.
This is a bounded subscription feed, not a complete archive; omissions remain
possible when posts disappear or the board changes rapidly.

A stable canonical article URL is the RSS GUID. Source dates are used when
available; an absent date gets its first collection time, preserved on later runs.

## DC post bodies

`article_content: true` in `sources.json` enables body collection per DC feed;
all five DC feeds are enabled. New posts are queued for one-time extraction of the
`.write_div` article container, excluding comments, navigation and surrounding ads.
Basic formatting, links and image URLs are kept in RSS `content:encoded`; scripts,
iframes, forms, event handlers and styling are removed. Video/audio become links.
Images are not downloaded, mirrored, OCRed or interpreted. Remote image access can
still fail (for example HTTP 403); successful HTML extraction does not prove that
images will display in a reader. This also does not identify promotional prose
inside a post or grant permission to republish third-party content.

Known `dcimgN.dcinside.co.kr` / `dcimgN.dcinside.com` image-file URLs are normalized
to `https://image.dcinside.com`, keeping `viewimage.php` or `dccon.php` and the
original query intact. The HTML viewer `viewimagePop.php` is not an image route.
Rendering also normalizes existing cached DC bodies without refetching posts;
official RSS feeds and ordinary links are untouched. For Miniflux's separate Download
behavior, see [the supported scraper/rewrite settings](docs/miniflux.md).

At most ten article requests per enabled feed are made in one run: at most fifty
across the five DC feeds, processed sequentially with two seconds between body
requests within each feed. This is a per-feed budget, not a shared host cooldown. Responses have a 1 MiB limit, connection/read timeouts and no
redirect following. Successful bodies are cached in durable state. Old entries
without body metadata are not automatically backfilled. Explicitly queued posts
are processed oldest first; sustained arrivals above capacity leave a backlog and
normal 1,000-item retention can eventually evict queued posts.

Temporary failures get at most three attempts, at least an hour apart. Forbidden,
unauthorized and deleted posts are not retried. HTTP 429 stops the feed's body work
and observes at least an hour of cooldown or a longer `Retry-After`. Failed/pending
bodies retain their title, link, GUID and date in state, but are not emitted as RSS
articles until a body is ready. Image-only bodies are valid; no image analysis is
required. Failed items remain visible in collection status rather than as empty
reader articles. Existing metadata-only history is preserved without backfill.
Published and retained item counts and body counts are shown separately in `status.json` and on the status page; they do
not turn an otherwise successful feed-list collection into an Actions failure.
Disabling collection stops new body work; it does not erase already stored bodies.

## Failures and notifications

Empty bodies, empty feeds, HTTP failures, unexpected DC markup and missing fields
are errors. Requests have timeouts and bounded retries. A failed source keeps its
last good XML byte-for-byte. Other sources continue updating. Status, state and
feeds are deployed before the workflow is marked failed. Temporary list-collection
transport errors (timeouts, connection errors, HTTP 429 and 5xx) fail Actions only
after the same source has failed at least three consecutive times AND its last
success was at least three hours ago. With no prior success, time is measured
from the first failure. Recovery resets the streak. Errors remain visible on the
status page even while notification is deferred; Actions success is not proof
that every source refreshed. Parser/validation, pagination-cap, rendering, state
storage, tests and deployment failures still fail immediately. Persistent failures
can continue to notify on subsequent runs, subject to GitHub notification settings.
A first-time failed source has no XML until it first succeeds.

The status page and `status.json` show each feed's last attempt, last successful
collection, last new article, item count and error. Times are UTC. These are static
snapshots: inspect the snapshot timestamp, not just the Healthy label. A stopped
scheduler cannot notify you about itself.

**Account setting required:** in GitHub Settings > Notifications > Actions,
enable email notifications for failed workflows (and ensure the relevant workflow
subscription is enabled). GitHub controls delivery according to your account's
notification settings; the repository cannot enable those settings for you.
Deployment/test/infrastructure failures also mark the workflow failed, but may
prevent the status page from updating. Check the Actions logs in that case.

## Local development

Requires Python 3.12 (tested locally and in GitHub Actions).

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python build.py
.venv/bin/python -m http.server --directory site 8000
```

`build.py` exits nonzero when a failure meets the alert policy above. Inspect
`site/` for successful feeds and the status report, including deferred errors.
Preserve `site/` between local runs to retain history.

## GitHub deployment

Pages must use the GitHub Actions build type. The workflow needs contents-write,
pages-write and id-token-write permissions. It restores the `data` branch,
collects feeds, commits updated state there and deploys a Pages artifact. All
source, article metadata and collection errors on that branch are public.
Workflow concurrency prevents overlapping runs from racing on the state branch.
Use Actions > Collect and publish feeds > Run workflow for manual collection.
No paid service credentials or external monitoring accounts are needed.

## Maintenance

Start with [AGENTS.md](AGENTS.md) and the [maintenance runbook](docs/maintenance.md).
The CLI is in `build.py`; collection, parsing, history and rendering live in
`rss_service/`. Install `requirements-dev.txt` for the pinned Black formatter.
