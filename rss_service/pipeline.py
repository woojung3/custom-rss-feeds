"""Per-source failure isolation and build orchestration."""

from datetime import datetime, timezone
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from .collection import collect
from .state import merge
from .rendering import write_feed, render_index

UTC = timezone.utc


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
        try:
            incoming, warning = collect(source, record["items"])
            known = {item["id"] for item in record["items"]}
            items = merge(record["items"], incoming, now)
            # Commit metadata only after the replacement RSS is safely written.
            write_feed(output / "feeds" / f"{key}.xml", source, items, now, base)
            if any(item["id"] not in known for item in incoming):
                record["last_new"] = now
            record["items"] = items
            record["last_success"] = now
            record["error"] = warning
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
        if record["error"]:
            failed = True
            print(f"FAILED {key}: {record['error']}", flush=True)
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
