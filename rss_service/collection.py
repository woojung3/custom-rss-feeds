"""Source routing and bounded DC pagination."""

import time
from urllib.parse import urlsplit, parse_qs, urlencode, urlunsplit
from .http import fetch
from .parsers import parse_rss, parse_dc

MAX_PAGES = 10


def collect(source, previous):
    if source["kind"] == "rss":
        return parse_rss(fetch(source["url"])), None
    if source["kind"] != "dc":
        raise ValueError(f"Unknown source kind: {source['kind']}")
    known = {item["id"] for item in previous}
    result = {}
    seen_pages = set()
    for page in range(1, MAX_PAGES + 1):
        parts = urlsplit(source["url"])
        query = parse_qs(parts.query)
        query.update({"page": [str(page)], "list_num": ["100"]})
        url = urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), "")
        )
        batch = parse_dc(fetch(url), url)
        signature = tuple(item["id"] for item in batch)
        if signature in seen_pages:
            raise ValueError(
                "Pagination repeated a page before reaching previous articles"
            )
        seen_pages.add(signature)
        result.update((item["id"], item) for item in batch)
        if not known or any(item["id"] in known for item in batch):
            return list(result.values()), None
        time.sleep(1)
    return (
        list(result.values()),
        "Pagination limit reached; some articles may have been missed",
    )
