"""Bounded network access."""

import time
import requests
from urllib.parse import urlsplit, parse_qs

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Referer": "https://gall.dcinside.com/",
}


MAX_ARTICLE_BYTES = 1024 * 1024


def fetch_article(url):
    """One bounded attempt; no redirects, cookies or embedded-media requests."""
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    if (
        parts.scheme not in ("https", "http")
        or parts.hostname != "gall.dcinside.com"
        or parts.username is not None
        or parts.password is not None
        or parts.port is not None
        or parts.path not in ("/board/view/", "/mgallery/board/view/")
        or not query.get("id")
        or not query.get("no", [""])[0].isdigit()
    ):
        raise ValueError("invalid_article_url")
    with requests.get(
        url, headers=HEADERS, timeout=(5, 10), stream=True, allow_redirects=False
    ) as response:
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError("unexpected_article_response")
        if "html" not in response.headers.get("Content-Type", "").lower():
            raise ValueError("unexpected_article_content_type")
        chunks = []
        size = 0
        started = time.monotonic()
        for chunk in response.iter_content(chunk_size=16384):
            size += len(chunk)
            if size > MAX_ARTICLE_BYTES:
                raise ValueError("article_too_large")
            if time.monotonic() - started > 20:
                raise ValueError("article_deadline")
            chunks.append(chunk)
        if not size:
            raise ValueError("empty_article_response")
        return b"".join(chunks)


def fetch(url):
    for attempt in range(3):
        try:
            response = requests.get(url, headers=HEADERS, timeout=40)
            response.raise_for_status()
            if not response.content.strip():
                raise ValueError("Empty response body")
            return response.content
        except (requests.RequestException, ValueError):
            if attempt == 2:
                raise
            time.sleep(2 ** (attempt + 1))
