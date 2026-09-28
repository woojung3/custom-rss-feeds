"""Stable item identity and retained history."""

MAX_ITEMS = 1000


def merge(previous, incoming, now):
    merged = {item["id"]: dict(item) for item in previous}
    for item in incoming:
        item = dict(item)
        old = merged.get(item["id"], {})
        item["date"] = item.get("date") or old.get("date") or now
        merged[item["id"]] = item
    return sorted(merged.values(), key=lambda item: item["date"], reverse=True)[
        :MAX_ITEMS
    ]
