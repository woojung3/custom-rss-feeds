"""Bounded network access."""

import time
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Referer": "https://gall.dcinside.com/",
}


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
