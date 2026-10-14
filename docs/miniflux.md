# Miniflux integration: DCInside feeds

Apply the same settings to `dcbest`, `ai-utilize`, `thesingularity`, `cartoon` and
`comic-new6`. Match the existing subscriptions by the exact public
`https://woojung3.github.io/custom-rss-feeds/feeds/{id}.xml` URL, using the DC IDs
from `sources.json`. Do not apply these settings to official RSS or unrelated
subscriptions, or enable automatic crawling. Miniflux's **Download / Fetch original
content** replaces the saved article body; it does not download image files.

## Supported settings

`integrations/miniflux-dcinside.json` contains the two shared supported feed
settings; subscription URLs are selected separately as described above:

- `scraper_rules`: `.write_div`, restricting Download to the DC post container.
- `rewrite_rules`: the official `add_dynamic_image` rule first resolves lazy image
  attributes (otherwise some posts show a loading GIF), followed by four narrow
  image-source replacements covering `dcimgN` on `dcinside.co.kr` and
  `dcinside.com`, and `viewimage.php` / `dccon.php` separately.

The replacements target image `src` attributes and use `image.dcinside.com` over
HTTPS. Paths and queries stay intact. Article URLs, ordinary links, unrelated
hosts and the HTML viewer `viewimagePop.php` are not rewritten. This is not an
image mirror, a Referer override or an access-control bypass.

The RSS generator performs the corresponding normalization on new bodies and
when rendering cached bodies for the enabled DC feeds. Cached bodies are not fetched
again or destructively rewritten. Metadata-only history is not backfilled.

## Validate before applying

Miniflux 2.3.3 tokenizes rule arguments as **Go string literals**, unquotes them,
then compiles the resulting regular expression. A regex backslash must therefore
be escaped at the string-literal layer as well as the outer JSON layer. Invalid
Go escapes can silently turn the search argument into an empty pattern; repeated
replacements may expand content catastrophically. Do not hand-remove escapes or
test unvalidated rules against a running service.

`rss_service.images.miniflux_rewrite_rules()` generates properly quoted arguments.
The offline Python tests check the checked-in recipe against that generator and
exercise string decoding before regex evaluation. Run those tests first:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Also validate with Go's actual scanner, string decoder and regular-expression
engine, offline and with bounded resources. Install/pull the test tool separately
if needed; the test itself has no network or service access:

```sh
docker pull golang:1.26-alpine
docker run --rm --network none --memory 512m --memory-swap 512m --cpus 1 \
  --pids-limit 128 --read-only --cap-drop ALL \
  --security-opt no-new-privileges --tmpfs /tmp:rw,exec,size=300m \
  -e GOCACHE=/tmp/gocache -e GO111MODULE=off -e GOTOOLCHAIN=local \
  -e GOMAXPROCS=1 -e GOFLAGS=-p=1 -v "$PWD:/work:ro" -w /work \
  golang:1.26-alpine go run tests/miniflux_rules.go \
  integrations/miniflux-dcinside.json
```

For the Miniflux UI, print the decoded `rewrite_rules` field and paste that exact
output, not the outer JSON string. Preserve its remaining escapes:

```sh
.venv/bin/python -c 'import json; print(json.load(open("integrations/miniflux-dcinside.json"))["rewrite_rules"])'
```

## Apply and verify with approval

1. Find the subscription by the exact `feed_url`; do not assume a portable feed ID.
2. Privately back up the old scraper/rewrite settings and any article body being
   repaired. Do not store credentials or account data in this repository.
3. Through the feed settings UI or `PUT /v1/feeds/{id}`, update **only**
   `scraper_rules` and `rewrite_rules`. Preserve crawler, filtering, credentials,
   category, title and subscription URL. Do not overwrite unrelated custom rules.
4. First use `GET /v1/entries/{id}/fetch-content?update_content=false`. Check that
   menus/comments are absent, expected article text and images remain, image
   paths/queries are intact, and saved content has not changed.
5. Only after that preview succeeds, use Download or the same API with
   `update_content=true` to replace the chosen article. Back up immediately before
   writing and inspect the result. Do not blindly retry an uncertain write or
   restore stale read/star state over a reader's concurrent actions.
6. Separately verify RSS refresh/ingestion after an authorized producer deployment.
   Do not infer updated RSS deployment from successful Download extraction.
7. Check actual images in Capy Reader. A successful server-side image request does
   not prove mobile rendering, OCR or interpretation of image contents.

Verified with Miniflux 2.3.3: one sample from each of the five boards produced the
same text and image URLs through the producer parser and native read-only
fetch-content path. Coverage includes lazy images and an image-only cartoon.
The first image from each sample returned an image signature without a Referer;
this does not verify every image or interpret its contents. Existing article
bodies and read/star states were unchanged by these previews.

The AI-utilize sample (467 characters, two images) also passed a native save and
both image downloads, and the user confirmed its images in Capy Reader. Actual
Capy rendering of the other boards has not been independently confirmed. Sample
coverage is not a guarantee for all DC media.

Download still replaces an inline AI summary along with the old body. These rules
do not preserve or reapply summaries; that lifecycle belongs to a future AI tool.
On a failed rule preview, restore only the backed-up settings, after checking for
concurrent changes. Do not delete subscriptions, reset history or touch PostgreSQL.

References: [official rules](https://miniflux.app/docs/rules.html),
[API](https://miniflux.app/docs/api.html), and the version-pinned
[rule parser](https://github.com/miniflux/v2/blob/2.3.3/internal/reader/rewrite/content_rewrite.go).
