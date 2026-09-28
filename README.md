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
Only titles, links, dates and available text excerpts are republished. Read full
articles at their original URLs. Respect source policies and access restrictions.

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

## Failures and notifications

Empty bodies, empty feeds, HTTP failures, unexpected DC markup and missing fields
are errors. Requests have timeouts and bounded retries. A failed source keeps its
last good XML byte-for-byte. Other sources continue updating. Status, state and
feeds are deployed before the workflow is marked failed. A first-time failed
source has no XML until it first succeeds.

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

`build.py` exits nonzero if any source fails; still inspect `site/` for successful
feeds and the status report. Preserve `site/` between local runs to retain history.

## GitHub deployment

Pages must use the GitHub Actions build type. The workflow needs contents-write,
pages-write and id-token-write permissions. It restores the `data` branch,
collects feeds, commits updated state there and deploys a Pages artifact. All
source, article metadata and collection errors on that branch are public.
Workflow concurrency prevents overlapping runs from racing on the state branch.
Use Actions > Collect and publish feeds > Run workflow for manual collection.
No paid service credentials or external monitoring accounts are needed.
