import argparse
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime, parsedate_to_datetime
import html
import json
from pathlib import Path
import time
from urllib.parse import urljoin, urlsplit, parse_qs, urlencode, urlunsplit
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

UTC = timezone.utc
KST = timezone(timedelta(hours=9))
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    'Referer': 'https://gall.dcinside.com/',
}
MAX_PAGES = 10
MAX_ITEMS = 1000


def fetch(url):
    for attempt in range(3):
        try:
            response = requests.get(url, headers=HEADERS, timeout=40)
            response.raise_for_status()
            if not response.content.strip():
                raise ValueError('Empty response body')
            return response.content
        except (requests.RequestException, ValueError):
            if attempt == 2:
                raise
            time.sleep(2 ** (attempt + 1))


def valid_link(link):
    parts = urlsplit(link)
    return parts.scheme in ('https', 'http') and bool(parts.netloc)


def parse_rss(data):
    root = ET.fromstring(data)
    items = []
    for node in root.findall('./channel/item'):
        title = (node.findtext('title') or '').strip()
        link = (node.findtext('link') or '').strip()
        if not title or not valid_link(link):
            raise ValueError('RSS item missing title or valid link')
        date = node.findtext('pubDate')
        if date:
            date = parsedate_to_datetime(date).astimezone(UTC).isoformat()
        # Only plain-text excerpts are republished; no remote scripts or images.
        summary = BeautifulSoup(node.findtext('description') or '', 'html.parser').get_text(' ', strip=True)[:1500]
        items.append({'id': link, 'title': title, 'link': link, 'date': date, 'summary': summary})
    if not items:
        raise ValueError('RSS contains zero items')
    return items


def parse_dc(data, url):
    soup = BeautifulSoup(data, 'html.parser')
    board = parse_qs(urlsplit(url).query)['id'][0]
    items = []
    for row in soup.select('tr.ub-content.us-post'):
        subject = row.select_one('.gall_subject')
        if 'notice' in row.get('data-type', '') or (subject and subject.get_text(strip=True) in ('공지', '설문', 'AD')):
            continue
        number = row.get('data-no', '')
        if not number.isdigit():
            continue
        anchor = row.select_one('.gall_tit a[href*="/board/view/"]')
        date_node = row.select_one('.gall_date')
        if anchor is None or date_node is None:
            raise ValueError('DC row missing title link or date')
        title = anchor.get_text(' ', strip=True)
        link = urljoin(url, anchor['href'])
        parts = urlsplit(link)
        query = parse_qs(parts.query)
        if not title or parts.hostname != 'gall.dcinside.com' or query.get('id') != [board] or query.get('no') != [number]:
            raise ValueError('Unexpected DC article link or title')
        link = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode({'id': board, 'no': number}), ''))
        date = datetime.strptime(date_node.get('title', ''), '%Y-%m-%d %H:%M:%S').replace(tzinfo=KST).astimezone(UTC).isoformat()
        items.append({'id': link, 'title': title, 'link': link, 'date': date, 'summary': ''})
    if not items:
        raise ValueError('DC list contains zero articles (blocked response or changed markup)')
    return items


def collect(source, previous):
    if source['kind'] == 'rss':
        return parse_rss(fetch(source['url'])), None
    known = {item['id'] for item in previous}
    result = {}
    seen_pages = set()
    for page in range(1, MAX_PAGES + 1):
        parts = urlsplit(source['url'])
        query = parse_qs(parts.query)
        query.update({'page': [str(page)], 'list_num': ['100']})
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), ''))
        batch = parse_dc(fetch(url), url)
        signature = tuple(item['id'] for item in batch)
        if signature in seen_pages:
            raise ValueError('Pagination repeated a page before reaching previous articles')
        seen_pages.add(signature)
        result.update((item['id'], item) for item in batch)
        if not known or any(item['id'] in known for item in batch):
            return list(result.values()), None
        time.sleep(1)
    return list(result.values()), 'Pagination limit reached; some articles may have been missed'


def merge(previous, incoming, now):
    merged = {item['id']: dict(item) for item in previous}
    for item in incoming:
        item = dict(item)
        old = merged.get(item['id'], {})
        item['date'] = item.get('date') or old.get('date') or now
        merged[item['id']] = item
    return sorted(merged.values(), key=lambda item: item['date'], reverse=True)[:MAX_ITEMS]


def write_feed(path, source, items, now, base):
    rss = ET.Element('rss', version='2.0')
    channel = ET.SubElement(rss, 'channel')
    for key, value in [('title', source['emoji'] + ' ' + source['name']), ('link', source['url']), ('description', source['name']), ('lastBuildDate', format_datetime(datetime.fromisoformat(now)))]:
        ET.SubElement(channel, key).text = value
    ET.SubElement(channel, '{http://www.w3.org/2005/Atom}link', href=f"{base}/feeds/{source['id']}.xml", rel='self', type='application/rss+xml')
    for item in items:
        node = ET.SubElement(channel, 'item')
        for key, value in [('title', source['emoji'] + ' ' + item['title']), ('link', item['link']), ('pubDate', format_datetime(datetime.fromisoformat(item['date']))), ('description', html.escape(item['summary']))]:
            ET.SubElement(node, key).text = value
        ET.SubElement(node, 'guid', isPermaLink='true').text = item['id']
    ET.indent(rss)
    ET.ElementTree(rss).write(path, encoding='utf-8', xml_declaration=True)


def build(output, base):
    sources = json.loads(Path('sources.json').read_text())
    output.mkdir(parents=True, exist_ok=True)
    (output / 'feeds').mkdir(exist_ok=True)
    state_path = output / 'state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    now = datetime.now(UTC).isoformat()
    failed = False
    statuses = []
    for source in sources:
        key = source['id']
        record = state.setdefault(key, {'items': [], 'last_success': None, 'last_new': None})
        record.update(last_attempt=now, error=None)
        try:
            incoming, warning = collect(source, record['items'])
            known = {item['id'] for item in record['items']}
            if any(item['id'] not in known for item in incoming):
                record['last_new'] = now
            record['items'] = merge(record['items'], incoming, now)
            record['last_success'] = now
            record['error'] = warning
            write_feed(output / 'feeds' / f'{key}.xml', source, record['items'], now, base)
        except Exception as exc:
            record['error'] = f'{type(exc).__name__}: {exc}'
        if record['error']:
            failed = True
            print(f"FAILED {key}: {record['error']}", flush=True)
        else:
            print(f"OK {key}: {len(record['items'])} items", flush=True)
        statuses.append({**{k: v for k, v in record.items() if k != 'items'}, 'id': key, 'name': source['name'], 'emoji': source['emoji'], 'count': len(record['items']), 'available': (output / 'feeds' / f'{key}.xml').exists()})
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    (output / 'status.json').write_text(json.dumps({'updated': now, 'feeds': statuses}, ensure_ascii=False, indent=2))
    render_index(output, statuses, now)
    opml = ET.Element('opml', version='2.0')
    ET.SubElement(ET.SubElement(opml, 'head'), 'title').text = 'Custom RSS Feeds'
    body = ET.SubElement(opml, 'body')
    for s in sources:
        ET.SubElement(body, 'outline', type='rss', text=s['emoji'] + ' ' + s['name'], title=s['name'], xmlUrl=f"{base}/feeds/{s['id']}.xml", htmlUrl=s['url'])
    ET.ElementTree(opml).write(output / 'subscriptions.opml', encoding='utf-8', xml_declaration=True)
    (output / '.nojekyll').touch()
    return failed


def render_index(output, statuses, now):
    cards = []
    for s in statuses:
        esc = lambda value: html.escape(str(value or 'Not yet'))
        cards.append(f'''<article><header><span>{s['emoji']}</span><h2>{esc(s['name'])}</h2></header>
<p class="{'error' if s['error'] else 'ok'}">{esc(s['error']) if s['error'] else 'Healthy'} &middot; {s['count']} items</p>
<dl><dt>Last attempt</dt><dd>{esc(s['last_attempt'])}</dd><dt>Last success</dt><dd>{esc(s['last_success'])}</dd><dt>Last new article</dt><dd>{esc(s['last_new'])}</dd></dl>
{'<a href="feeds/' + s['id'] + '.xml">Subscribe RSS &rarr;</a>' if s['available'] else '<p>Awaiting first successful collection</p>'}</article>''')
    (output / 'index.html').write_text('''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Signal / RSS Observatory</title><style>
:root{--ink:#17382f;--paper:#f4f0df;--accent:#c24725}*{box-sizing:border-box}body{margin:0;color:var(--ink);background:radial-gradient(ellipse at top right,#e1e9c9,transparent 65%),var(--paper);font-family:Georgia,serif}main{max-width:1200px;margin:auto;padding:60px 24px}h1{font-size:clamp(3rem,9vw,7rem);font-weight:normal;margin:20px 0}h2{font-size:1.3rem}a{color:var(--ink);text-underline-offset:5px}.eyebrow{letter-spacing:.2em;text-transform:uppercase}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:20px;margin:40px 0}article{border-top:3px solid var(--ink);padding:18px;background:#ffffff66;animation:enter .5s ease-out}header{display:flex;align-items:center;gap:12px}header span{font-size:1.8rem}dt{font-size:.8rem;text-transform:uppercase;margin-top:12px}dd{margin:4px 0;font-family:monospace;overflow-wrap:anywhere}.error{color:#9f291a;overflow-wrap:anywhere}.ok{color:#28633e}footer{font-size:.9rem}@keyframes enter{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}@media(prefers-reduced-motion:reduce){article{animation:none}}
</style><main><p class="eyebrow">Seven sources / hourly collection</p><h1>Signal, not silence.</h1><p>RSS Observatory &mdash; failures stay visible. Last good feeds stay available.</p><p><a href="subscriptions.opml">Import all feeds (OPML)</a> &nbsp; <a href="status.json">Status JSON</a></p><p>Snapshot: ''' + html.escape(now) + ''' &middot; All times UTC.</p><p>This is a static snapshot, not a live monitor. No new articles does not mean collection failed.</p><section class="grid">''' + ''.join(cards) + '''</section><footer>Titles, links and available excerpts only. No external heartbeat monitoring. GitHub Actions runs hourly at :17 UTC; schedules may be delayed.</footer></main></html>''')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('site'))
    parser.add_argument('--base-url', default='https://woojung3.github.io/custom-rss-feeds')
    args = parser.parse_args()
    raise SystemExit(1 if build(args.output, args.base_url.rstrip('/')) else 0)
