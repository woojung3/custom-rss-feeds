"""Stable item identity and retained history."""

from .article import CONTENT_FIELDS

MAX_ITEMS = 1000


def merge(previous, incoming, now):
    merged = {item["id"]: dict(item) for item in previous}
    for item in incoming:
        item = dict(item)
        old = merged.get(item["id"], {})
        item["date"] = item.get("date") or old.get("date") or now
        for field in CONTENT_FIELDS:
            if field not in item and field in old:
                item[field] = old[field]
        if old.get("content_html") and not item.get("summary"):
            item["summary"] = old.get("summary", "")
        merged[item["id"]] = item
    return sorted(merged.values(), key=lambda item: item["date"], reverse=True)[
        :MAX_ITEMS
    ]
