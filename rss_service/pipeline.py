"""Per-source failure isolation and build orchestration."""

from datetime import datetime, timezone
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import requests
from .collection import collect
from .article import enrich
from .state import merge
from .rendering import write_feed, render_index

UTC = timezone.utc


def is_transient(exc):
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return exc.response.status_code == 429 or 500 <= exc.response.status_code < 600
    return False


def update_alert(record, now, transient):
    """Persist streaks; suppress only temporary collection transport failures."""
    if not record["error"]:
        record.update(consecutive_failures=0, first_failure=None, alert_required=False)
        return False
    record["consecutive_failures"] = record.get("consecutive_failures", 0) + 1
    record["first_failure"] = record.get("first_failure") or now
    baseline = record.get("last_success") or record["first_failure"]
    elapsed = (
        datetime.fromisoformat(now) - datetime.fromisoformat(baseline)
    ).total_seconds()
    alert = not transient or (record["consecutive_failures"] >= 3 and elapsed >= 10800)
    record["alert_required"] = alert
    return alert


def build(output, base):
    sources = json.loads(Path("sources.json").read_text())
    output.mkdir(parents=True, exist_ok=True)
    (output / "feeds").mkdir(exist_ok=True)
    state_path = output / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    now = datetime.now(UTC).isoformat()
    failed = False
    statuses = []
    for source in sources:
        key = source["id"]
        record = state.setdefault(
            key, {"items": [], "last_success": None, "last_new": None}
        )
        record.update(last_attempt=now, error=None)
        collecting = True
        transient = False
        try:
            incoming, warning = collect(source, record["items"])
            collecting = False
            known = {item["id"] for item in record["items"]}
            items = merge(record["items"], incoming, now)
            body_collection = enrich(
                source, items, known, datetime.now(UTC).isoformat()
            )
            # Commit metadata only after the replacement RSS is safely written.
            published_count = write_feed(
                output / "feeds" / f"{key}.xml", source, items, now, base
            )
            if any(item["id"] not in known for item in incoming):
                record["last_new"] = now
            record["items"] = items
            record["published_count"] = published_count
            if body_collection is not None:
                record["body_collection"] = body_collection
            else:
                record.pop("body_collection", None)
            record["last_success"] = now
            record["error"] = warning
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
            transient = collecting and is_transient(exc)
        alert = update_alert(record, now, transient)
        failed = failed or alert
        if record["error"]:
            level = "FAILED" if alert else "DEFERRED"
            print(f"{level} {key}: {record['error']}", flush=True)
        else:
            print(f"OK {key}: {len(record['items'])} items", flush=True)
        statuses.append(
            {
                **{k: v for k, v in record.items() if k != "items"},
                "id": key,
                "name": source["name"],
                "emoji": source["emoji"],
                "count": len(record["items"]),
                "available": (output / "feeds" / f"{key}.xml").exists(),
            }
        )
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    (output / "status.json").write_text(
        json.dumps({"updated": now, "feeds": statuses}, ensure_ascii=False, indent=2)
    )
    render_index(output, statuses, now)
    opml = ET.Element("opml", version="2.0")
    ET.SubElement(ET.SubElement(opml, "head"), "title").text = "Custom RSS Feeds"
    body = ET.SubElement(opml, "body")
    for s in sources:
        ET.SubElement(
            body,
            "outline",
            type="rss",
            text=s["emoji"] + " " + s["name"],
            title=s["name"],
            xmlUrl=f"{base}/feeds/{s['id']}.xml",
            htmlUrl=s["url"],
        )
    ET.ElementTree(opml).write(
        output / "subscriptions.opml", encoding="utf-8", xml_declaration=True
    )
    (output / ".nojekyll").touch()
    return failed
