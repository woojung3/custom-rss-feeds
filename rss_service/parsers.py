"""Pure source parsers; no network or filesystem access."""

from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit, parse_qs, urlencode, urlunsplit
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup

UTC = timezone.utc
KST = timezone(timedelta(hours=9))


def valid_link(link):
    parts = urlsplit(link)
    return parts.scheme in ("https", "http") and bool(parts.netloc)


def parse_rss(data):
    root = ET.fromstring(data)
    items = []
    for node in root.findall("./channel/item"):
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        if not title or not valid_link(link):
            raise ValueError("RSS item missing title or valid link")
        date = node.findtext("pubDate")
        if date:
            date = parsedate_to_datetime(date).astimezone(UTC).isoformat()
        # Only plain-text excerpts are republished; no remote scripts or images.
        summary = BeautifulSoup(
            node.findtext("description") or "", "html.parser"
        ).get_text(" ", strip=True)[:1500]
        items.append(
            {"id": link, "title": title, "link": link, "date": date, "summary": summary}
        )
    if not items:
        raise ValueError("RSS contains zero items")
    return items


def parse_dc(data, url):
    soup = BeautifulSoup(data, "html.parser")
    board = parse_qs(urlsplit(url).query)["id"][0]
    items = []
    for row in soup.select("tr.ub-content.us-post"):
        subject = row.select_one(".gall_subject")
        if "notice" in row.get("data-type", "") or (
            subject and subject.get_text(strip=True) in ("공지", "설문", "AD")
        ):
            continue
        number = row.get("data-no", "")
        if not number.isdigit():
            continue
        anchor = row.select_one('.gall_tit a[href*="/board/view/"]')
        date_node = row.select_one(".gall_date")
        if anchor is None or date_node is None:
            raise ValueError("DC row missing title link or date")
        title = anchor.get_text(" ", strip=True)
        link = urljoin(url, anchor["href"])
        parts = urlsplit(link)
        query = parse_qs(parts.query)
        if (
            not title
            or parts.hostname != "gall.dcinside.com"
            or query.get("id") != [board]
            or query.get("no") != [number]
        ):
            raise ValueError("Unexpected DC article link or title")
        link = urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                parts.path,
                urlencode({"id": board, "no": number}),
                "",
            )
        )
        date = (
            datetime.strptime(date_node.get("title", ""), "%Y-%m-%d %H:%M:%S")
            .replace(tzinfo=KST)
            .astimezone(UTC)
            .isoformat()
        )
        items.append(
            {"id": link, "title": title, "link": link, "date": date, "summary": ""}
        )
    if not items:
        raise ValueError(
            "DC list contains zero articles (blocked response or changed markup)"
        )
    return items
