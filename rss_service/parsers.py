"""Pure source parsers; no network or filesystem access."""

from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit, parse_qs, urlencode, urlunsplit
import xml.etree.ElementTree as ET
import re
from bs4 import BeautifulSoup, Comment

from .images import normalize_dc_image_url

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


def content_url(value, base):
    """Allow ordinary web links only, never credentials or active URL schemes."""
    if (
        not isinstance(value, str)
        or not value.strip()
        or any(ord(c) < 32 for c in value)
    ):
        return None
    try:
        url = urljoin(base, value.strip())
        parts = urlsplit(url)
        if (
            not valid_link(url)
            or parts.username is not None
            or parts.password is not None
        ):
            return None
        return url
    except ValueError:
        return None


def parse_dc_article(data, url):
    """Extract the post, not comments/navigation. Never fetch embedded media."""
    soup = BeautifulSoup(data, "html.parser")
    bodies = soup.select(".write_div")
    if len(bodies) != 1:
        raise ValueError("missing_article_container")
    body = bodies[0]
    for node in body.find_all(
        [
            "script",
            "style",
            "iframe",
            "form",
            "input",
            "button",
            "select",
            "textarea",
            "object",
            "embed",
            "svg",
            "math",
            "link",
            "meta",
            "base",
            "noscript",
        ]
    ):
        node.decompose()
    for node in body.find_all(string=lambda text: isinstance(text, Comment)):
        node.extract()
    for node in body.find_all(["video", "audio"]):
        source = node.find("source")
        href = content_url(
            node.get("src") or (source.get("src") if source else ""), url
        )
        if href:
            anchor = soup.new_tag("a", href=href)
            anchor.string = "원문 미디어 보기"
            node.replace_with(anchor)
        else:
            node.decompose()
    allowed = {
        "p",
        "div",
        "span",
        "br",
        "hr",
        "a",
        "img",
        "strong",
        "b",
        "em",
        "i",
        "u",
        "s",
        "blockquote",
        "pre",
        "code",
        "ul",
        "ol",
        "li",
        "h2",
        "h3",
        "h4",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "figure",
        "figcaption",
        "dl",
        "dt",
        "dd",
    }
    for node in list(body.find_all(True)):
        if node.name not in allowed:
            node.unwrap()
            continue
        attrs = dict(node.attrs)
        node.attrs = {}
        if node.name == "a":
            href = content_url(attrs.get("href", ""), url)
            if href:
                node["href"] = href
            else:
                node.unwrap()
        elif node.name == "img":
            src = next(
                (
                    candidate
                    for key in ("data-original", "data-src", "src")
                    if attrs.get(key) and (candidate := content_url(attrs[key], url))
                ),
                None,
            )
            if not src:
                node.decompose()
                continue
            node["src"] = normalize_dc_image_url(src)
            if attrs.get("alt"):
                node["alt"] = str(attrs["alt"])[:500]
    text = body.get_text(" ", strip=True)
    images = len(body.find_all("img"))
    if not text and not images:
        raise ValueError("empty_article_container")
    content = "".join(str(child) for child in body.contents).strip()
    content = re.sub(
        r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]", "", content
    )
    return {
        "content_html": content,
        "content_image_count": images,
        "content_status": "ready" if text else "image_only",
        "summary": re.sub(
            r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]", "", text
        )[:1500],
    }


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
