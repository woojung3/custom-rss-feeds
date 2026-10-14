"""Opt-in DC body enrichment with persistent, bounded work per article."""

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import time

import requests

from .http import fetch_article
from .parsers import parse_dc_article

MAX_FETCHES = 10
MAX_ATTEMPTS = 3
RETRY_AFTER = timedelta(hours=1)
REQUEST_GAP = 2
CONTENT_FIELDS = (
    "content_html",
    "content_status",
    "content_image_count",
    "content_attempts",
    "content_checked_at",
    "content_retry_at",
    "content_error",
)


def enrich(source, items, known, now):
    """Preserve old metadata-only entries; drain explicitly queued new items."""
    if source["kind"] != "dc" or not source.get("article_content", False):
        return None
    instant = datetime.fromisoformat(now)
    started = time.monotonic()
    for item in items:
        if item["id"] not in known and "content_status" not in item:
            item.update(content_status="pending", content_attempts=0)
    attempts = 0
    cooldown = any(
        item.get("content_retry_at")
        and datetime.fromisoformat(item["content_retry_at"]) > instant
        for item in items
    )
    # Oldest pending first: new traffic must not starve already queued entries.
    for item in sorted(items, key=lambda item: item["date"]):
        if (
            cooldown
            or item.get("content_status") != "pending"
            or attempts >= MAX_FETCHES
        ):
            continue
        if item.get("content_attempts", 0) >= MAX_ATTEMPTS:
            item["content_status"] = "failed"
            continue
        checked = item.get("content_checked_at")
        if checked and instant - datetime.fromisoformat(checked) < RETRY_AFTER:
            continue
        if attempts:
            time.sleep(REQUEST_GAP)
        attempts += 1
        item["content_attempts"] = item.get("content_attempts", 0) + 1
        item["content_checked_at"] = (
            instant + timedelta(seconds=time.monotonic() - started)
        ).isoformat()
        try:
            result = parse_dc_article(fetch_article(item["link"]), item["link"])
        except (requests.RequestException, ValueError) as error:
            status = getattr(getattr(error, "response", None), "status_code", None)
            item["content_error"] = f"HTTP {status}" if status else type(error).__name__
            # Do not repeatedly request forbidden/deleted posts. Network and
            # parser failures get at most three hourly attempts, not a tight loop.
            if (
                status in (401, 403, 404, 410)
                or item["content_attempts"] >= MAX_ATTEMPTS
            ):
                item["content_status"] = "failed"
            # Respect rate limiting by stopping this feed's body work for now.
            if status == 429:
                response_time = instant + timedelta(seconds=time.monotonic() - started)
                retry_at = response_time + RETRY_AFTER
                value = error.response.headers.get("Retry-After", "")
                try:
                    advised = (
                        response_time + timedelta(seconds=int(value))
                        if value.isdigit()
                        else parsedate_to_datetime(value)
                    )
                    if advised.tzinfo is None:
                        advised = advised.replace(tzinfo=timezone.utc)
                    retry_at = max(retry_at, advised)
                except (ValueError, TypeError, OverflowError):
                    pass
                item["content_retry_at"] = retry_at.isoformat()
                break
        else:
            item.update(result)
            item["content_error"] = None
    pending = sum(item.get("content_status") == "pending" for item in items)
    failed = sum(item.get("content_status") == "failed" for item in items)
    ready = sum(item.get("content_status") in ("ready", "image_only") for item in items)
    return {"ready": ready, "pending": pending, "failed": failed, "attempted": attempts}
