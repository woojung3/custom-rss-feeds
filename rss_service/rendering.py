"""Static RSS and health page output."""

from datetime import datetime
from email.utils import format_datetime
import html
import xml.etree.ElementTree as ET


def write_feed(path, source, items, now, base):
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    for key, value in [
        ("title", source["emoji"] + " " + source["name"]),
        ("link", source["url"]),
        ("description", source["name"]),
        ("lastBuildDate", format_datetime(datetime.fromisoformat(now))),
    ]:
        ET.SubElement(channel, key).text = value
    ET.SubElement(
        channel,
        "{http://www.w3.org/2005/Atom}link",
        href=f"{base}/feeds/{source['id']}.xml",
        rel="self",
        type="application/rss+xml",
    )
    for item in items:
        node = ET.SubElement(channel, "item")
        for key, value in [
            ("title", source["emoji"] + " " + item["title"]),
            ("link", item["link"]),
            ("pubDate", format_datetime(datetime.fromisoformat(item["date"]))),
            ("description", html.escape(item["summary"])),
        ]:
            ET.SubElement(node, key).text = value
        ET.SubElement(node, "guid", isPermaLink="true").text = item["id"]
    ET.indent(rss)
    temporary = path.with_suffix(".xml.tmp")
    try:
        ET.ElementTree(rss).write(temporary, encoding="utf-8", xml_declaration=True)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def render_index(output, statuses, now):
    cards = []
    for s in statuses:
        esc = lambda value: html.escape(str(value or "Not yet"))
        cards.append(
            f"""<article><header><span>{s['emoji']}</span><h2>{esc(s['name'])}</h2></header>
<p class="{'error' if s['error'] else 'ok'}">{esc(s['error']) if s['error'] else 'Healthy'} &middot; {s['count']} items</p>
<dl><dt>Last attempt</dt><dd>{esc(s['last_attempt'])}</dd><dt>Last success</dt><dd>{esc(s['last_success'])}</dd><dt>Last new article</dt><dd>{esc(s['last_new'])}</dd></dl>
{'<a href="feeds/' + s['id'] + '.xml">Subscribe RSS &rarr;</a>' if s['available'] else '<p>Awaiting first successful collection</p>'}</article>"""
        )
    (output / "index.html").write_text(
        """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Signal / RSS Observatory</title><style>
:root{--ink:#17382f;--paper:#f4f0df;--accent:#c24725}*{box-sizing:border-box}body{margin:0;color:var(--ink);background:radial-gradient(ellipse at top right,#e1e9c9,transparent 65%),var(--paper);font-family:Georgia,serif}main{max-width:1200px;margin:auto;padding:60px 24px}h1{font-size:clamp(3rem,9vw,7rem);font-weight:normal;margin:20px 0}h2{font-size:1.3rem}a{color:var(--ink);text-underline-offset:5px}.eyebrow{letter-spacing:.2em;text-transform:uppercase}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:20px;margin:40px 0}article{border-top:3px solid var(--ink);padding:18px;background:#ffffff66;animation:enter .5s ease-out}header{display:flex;align-items:center;gap:12px}header span{font-size:1.8rem}dt{font-size:.8rem;text-transform:uppercase;margin-top:12px}dd{margin:4px 0;font-family:monospace;overflow-wrap:anywhere}.error{color:#9f291a;overflow-wrap:anywhere}.ok{color:#28633e}footer{font-size:.9rem}@keyframes enter{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}@media(prefers-reduced-motion:reduce){article{animation:none}}
</style><main><p class="eyebrow">Seven sources / hourly collection</p><h1>Signal, not silence.</h1><p>RSS Observatory &mdash; failures stay visible. Last good feeds stay available.</p><p><a href="subscriptions.opml">Import all feeds (OPML)</a> &nbsp; <a href="status.json">Status JSON</a></p><p>Snapshot: """
        + html.escape(now)
        + """ &middot; All times UTC.</p><p>This is a static snapshot, not a live monitor. No new articles does not mean collection failed.</p><section class="grid">"""
        + "".join(cards)
        + """</section><footer>Titles, links and available excerpts only. No external heartbeat monitoring. GitHub Actions runs hourly at :17 UTC; schedules may be delayed.</footer></main></html>"""
    )
