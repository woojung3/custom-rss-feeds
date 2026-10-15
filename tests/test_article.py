from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
import requests

from rss_service import article, http, parsers, pipeline, rendering, state

NOW = "2026-10-14T00:00:00+00:00"
LATER = "2026-10-14T01:00:00+00:00"
SOURCE = {
    "id": "ai-utilize",
    "kind": "dc",
    "name": "Test",
    "emoji": "X",
    "article_content": True,
    "url": "https://gall.dcinside.com/mgallery/board/lists/?id=ai_utilize&exception_mode=recommend",
}
URL = "https://gall.dcinside.com/mgallery/board/view/?id=ai_utilize&no=123"
HTML = (Path(__file__).parent / "fixtures/dc-article.html").read_bytes()


def item(number=123):
    url = URL.replace("no=123", "no=" + str(number))
    return {"id": url, "link": url, "title": "Example", "summary": "", "date": NOW}


def http_error(code, retry=None):
    response = requests.Response()
    response.status_code = code
    if retry is not None:
        response.headers["Retry-After"] = retry
    return requests.HTTPError(response=response)


class Offline(unittest.TestCase):
    def setUp(self):
        for target, kwargs in [
            ("requests.get", {"side_effect": AssertionError("unexpected network")}),
            ("rss_service.article.time.sleep", {}),
            ("rss_service.article.time.monotonic", {"return_value": 0}),
        ]:
            guard = patch(target, **kwargs)
            guard.start()
            self.addCleanup(guard.stop)


class ParserTests(Offline):
    def test_only_article_and_safe_html(self):
        result = parsers.parse_dc_article(HTML, URL)
        content = result["content_html"]
        self.assertIn("짧은 본문", content)
        self.assertEqual(result["content_image_count"], 1)
        self.assertEqual(result["content_status"], "ready")
        for bad in (
            "OUTSIDE",
            "INSIDE SCRIPT",
            "FRAME TEXT",
            "FORM TEXT",
            "SVG SCRIPT",
            "HTML COMMENT",
            "onclick",
            "onerror",
            "style=",
            "javascript:",
            "placeholder.gif",
        ):
            self.assertNotIn(bad, content)
        self.assertIn("no=99", content)
        self.assertIn("https://gall.dcinside.com/board/view/", content)
        self.assertIn("image.dcinside.com/viewimage.php", content)
        self.assertEqual(
            BeautifulSoup(content, "html.parser").img["alt"], "Example & diagram"
        )

    def test_image_only_is_valid_but_no_image_content_is_inferred(self):
        result = parsers.parse_dc_article(
            '<div class="write_div"><img src="//dcimg1.dcinside.co.kr/a.jpg"></div>',
            URL,
        )
        self.assertEqual(result["content_status"], "image_only")
        self.assertEqual(result["summary"], "")
        self.assertEqual(result["content_image_count"], 1)

    def test_empty_missing_ambiguous_and_active_only_are_errors(self):
        for html in (
            "",
            "<html>Forbidden</html>",
            '<div class="write_div"></div>',
            '<div class="write_div">a</div><div class="write_div">b</div>',
            '<div class="write_div"><script>x</script><img src="data:image/png,abc"></div>',
        ):
            with self.subTest(html=html), self.assertRaises(ValueError):
                parsers.parse_dc_article(html, URL)

    def test_media_becomes_link_and_unsafe_urls_are_removed(self):
        result = parsers.parse_dc_article(
            """<div class="write_div"><video controls autoplay><source src="/movie.mp4"></video>
        <img src="javascript:alert(1)"><img src="https://user:pass@example.com/private">
        <a href="data:text/html,x">Label</a><a href="">Empty</a></div>""",
            URL,
        )
        self.assertIn(
            'href="https://gall.dcinside.com/movie.mp4"', result["content_html"]
        )
        self.assertNotIn("<video", result["content_html"])
        self.assertEqual(result["content_image_count"], 0)
        for bad in ("javascript", "user:pass", "data:text"):
            self.assertNotIn(bad, result["content_html"])

    def test_xml_roundtrip_and_stable_guid(self):
        value = item()
        value.update(parsers.parse_dc_article(HTML, URL))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feed.xml"
            rendering.write_feed(path, SOURCE, [value], NOW, "https://example.com")
            node = ET.parse(path).find("./channel/item")
            self.assertEqual(node.findtext("guid"), URL)
            self.assertEqual(node.findtext("link"), URL)
            self.assertEqual(
                node.findtext("{http://purl.org/rss/1.0/modules/content/}encoded"),
                value["content_html"],
            )
            self.assertNotIn("<script", node.findtext("description"))

    def test_pending_and_failed_bodies_are_retained_but_not_published(self):
        pending = dict(item(1), content_status="pending", content_attempts=0)
        failed = dict(item(2), content_status="failed", content_attempts=3)
        legacy = item(3)
        values = [pending, failed, legacy]
        before = json.loads(json.dumps(values))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feed.xml"
            self.assertEqual(
                rendering.write_feed(path, SOURCE, values, NOW, "https://example.com"),
                1,
            )
            self.assertEqual(
                [n.findtext("guid") for n in ET.parse(path).findall("./channel/item")],
                [legacy["id"]],
            )
        self.assertEqual(values, before)

    def test_ready_late_image_only_body_keeps_original_guid_and_date(self):
        value = dict(item(), content_status="pending", content_attempts=0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feed.xml"
            self.assertEqual(
                rendering.write_feed(path, SOURCE, [value], NOW, "https://example.com"),
                0,
            )
            value.update(
                parsers.parse_dc_article(
                    '<div class="write_div"><img src="https://example.org/image.jpg"></div>',
                    URL,
                )
            )
            self.assertEqual(
                rendering.write_feed(
                    path, SOURCE, [value], LATER, "https://example.com"
                ),
                1,
            )
            node = ET.parse(path).find("./channel/item")
            self.assertEqual(node.findtext("guid"), URL)
            self.assertEqual(value["date"], NOW)
            self.assertIn("14 Oct 2026 00:00:00", node.findtext("pubDate"))
            self.assertIn(
                "<img",
                node.findtext("{http://purl.org/rss/1.0/modules/content/}encoded"),
            )
            self.assertNotIn("수집 대기", path.read_text())

    def test_disabled_collection_cannot_publish_existing_pending_placeholders(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feed.xml"
            self.assertEqual(
                rendering.write_feed(
                    path,
                    dict(SOURCE, article_content=False),
                    [dict(item(), content_status="pending")],
                    NOW,
                    "https://example.com",
                ),
                0,
            )

    def test_invalid_xml_characters_removed(self):
        result = parsers.parse_dc_article(
            '<div class="write_div">A\x00B\x01C</div>', URL
        )
        self.assertNotIn("\x00", result["content_html"])
        self.assertNotIn("\x01", result["summary"])


class EnrichmentTests(Offline):
    def test_each_enabled_dc_feed_enriches_new_items_without_backfill(self):
        for source in json.loads(Path("sources.json").read_text()):
            if source["kind"] != "dc":
                continue
            with self.subTest(source=source["id"]):
                parts = urlsplit(source["url"])
                board = parse_qs(parts.query)["id"][0]
                base = "https://gall.dcinside.com" + parts.path.replace(
                    "/lists/", "/view/"
                )
                old, new = item(1), item(2)
                for number, value in enumerate((old, new), 1):
                    value["id"] = value["link"] = f"{base}?id={board}&no={number}"
                with patch(
                    "rss_service.article.fetch_article", return_value=HTML
                ) as fetch:
                    report = article.enrich(source, [old, new], {old["id"]}, NOW)
                fetch.assert_called_once_with(new["link"])
                self.assertEqual(report["ready"], 1)
                self.assertNotIn("content_status", old)
                self.assertIn("image.dcinside.com/viewimage.php", new["content_html"])
                self.assertEqual(new["date"], NOW)
                with patch("rss_service.article.fetch_article") as fetch:
                    article.enrich(source, [old, new], {old["id"], new["id"]}, LATER)
                fetch.assert_not_called()

    def test_opt_in_and_no_legacy_backfill(self):
        value = item()
        with patch("rss_service.article.fetch_article") as fetch:
            self.assertIsNone(
                article.enrich(dict(SOURCE, article_content=False), [value], set(), NOW)
            )
            result = article.enrich(SOURCE, [value], {value["id"]}, NOW)
        fetch.assert_not_called()
        self.assertNotIn("content_status", value)
        self.assertEqual(result["attempted"], 0)

    def test_bounded_work_and_persistent_queue(self):
        values = [item(n) for n in range(1, 5)]
        with patch("rss_service.article.MAX_FETCHES", 2), patch(
            "rss_service.article.fetch_article", return_value=HTML
        ) as fetch:
            report = article.enrich(SOURCE, values, set(), NOW)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(
            report, {"ready": 2, "pending": 2, "failed": 0, "attempted": 2}
        )
        known = {v["id"] for v in values}
        merged = state.merge(values, [item(1), item(3)], LATER)
        with patch("rss_service.article.fetch_article", return_value=HTML) as fetch:
            report = article.enrich(SOURCE, merged, known, LATER)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(report["ready"], 4)
        self.assertTrue(all(v["content_attempts"] == 1 for v in merged))
        self.assertTrue(all(v["date"] == NOW for v in merged))

    def test_ready_content_survives_overlapping_list_pages(self):
        original = item()
        with patch("rss_service.article.fetch_article", return_value=HTML):
            article.enrich(SOURCE, [original], set(), NOW)
        merged = state.merge([original], [item()], LATER)
        with patch("rss_service.article.fetch_article") as fetch:
            article.enrich(SOURCE, merged, {URL}, LATER)
        fetch.assert_not_called()
        self.assertEqual(merged[0], original)

    def test_failure_does_not_stop_other_items_or_invent_body(self):
        values = [item(1), item(2)]
        with patch(
            "rss_service.article.fetch_article", side_effect=[http_error(404), HTML]
        ):
            result = article.enrich(SOURCE, values, set(), NOW)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["ready"], 1)
        self.assertNotIn("content_html", values[0])
        self.assertEqual(values[0]["content_error"], "HTTP 404")

    def test_retry_budget_and_hourly_cooldown(self):
        values = [item()]
        with patch(
            "rss_service.article.fetch_article", side_effect=requests.Timeout
        ) as fetch:
            article.enrich(SOURCE, values, set(), NOW)
            article.enrich(SOURCE, values, {URL}, NOW)
            self.assertEqual(fetch.call_count, 1)
            article.enrich(SOURCE, values, {URL}, LATER)
            article.enrich(SOURCE, values, {URL}, "2026-10-14T02:00:00+00:00")
            article.enrich(SOURCE, values, {URL}, "2026-10-14T03:00:00+00:00")
            self.assertEqual(fetch.call_count, 3)
        self.assertEqual(values[0]["content_status"], "failed")

    def test_rate_limit_stops_feed_and_respects_retry_after(self):
        for retry in ("7200", "Wed, 14 Oct 2026 02:00:00 GMT"):
            values = [item(1), item(2)]
            with self.subTest(retry=retry), patch(
                "rss_service.article.fetch_article", side_effect=http_error(429, retry)
            ) as fetch:
                report = article.enrich(SOURCE, values, set(), NOW)
                self.assertEqual(report["attempted"], 1)
                article.enrich(SOURCE, values, {v["id"] for v in values}, LATER)
                self.assertEqual(fetch.call_count, 1)
            with patch("rss_service.article.fetch_article", return_value=HTML) as fetch:
                report = article.enrich(
                    SOURCE,
                    values,
                    {v["id"] for v in values},
                    "2026-10-14T02:00:00+00:00",
                )
            self.assertEqual(report["ready"], 2)

    def test_pipeline_body_failure_retains_metadata_and_status_not_empty_article(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "rss_service.pipeline.collect", return_value=([item()], None)
        ), patch("rss_service.article.fetch_article", side_effect=http_error(403)):
            output = Path(directory)
            self.assertFalse(pipeline.build(output, "https://example.com"))
            saved = json.loads((output / "state.json").read_text())["ai-utilize"]
            self.assertIsNone(saved["error"])
            self.assertEqual(saved["body_collection"]["failed"], 1)
            node = ET.parse(output / "feeds/ai-utilize.xml").find("./channel/item")
            self.assertIsNone(node)
            self.assertEqual(saved["items"][0]["id"], URL)
            self.assertEqual(saved["published_count"], 0)
            self.assertIn("1 unavailable", (output / "index.html").read_text())

    def test_hidden_pending_job_survives_restart_and_leaving_list(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch(
                "rss_service.pipeline.collect", return_value=([item()], None)
            ), patch("rss_service.article.MAX_FETCHES", 0):
                self.assertFalse(pipeline.build(output, "https://example.com"))
            saved = json.loads((output / "state.json").read_text())["ai-utilize"]
            self.assertEqual(saved["items"][0]["content_status"], "pending")
            self.assertEqual(saved["published_count"], 0)
            with patch("rss_service.pipeline.collect", return_value=([], None)), patch(
                "rss_service.article.fetch_article", return_value=HTML
            ):
                self.assertFalse(pipeline.build(output, "https://example.com"))
            saved = json.loads((output / "state.json").read_text())["ai-utilize"]
            self.assertEqual(saved["published_count"], 1)
            self.assertEqual(saved["items"][0]["date"], NOW)
            self.assertEqual(
                ET.parse(output / "feeds/ai-utilize.xml").findtext(
                    "./channel/item/guid"
                ),
                URL,
            )
            status = json.loads((output / "status.json").read_text())
            self.assertEqual(
                next(f for f in status["feeds"] if f["id"] == "ai-utilize")[
                    "published_count"
                ],
                1,
            )

    def test_render_failure_preserves_old_body_and_success_state(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "rss_service.pipeline.collect", return_value=([item()], None)
        ), patch("rss_service.article.fetch_article", return_value=HTML):
            output = Path(directory)
            pipeline.build(output, "https://example.com")
            before = json.loads((output / "state.json").read_text())["ai-utilize"]
            xml = (output / "feeds/ai-utilize.xml").read_bytes()
            with patch(
                "rss_service.pipeline.collect", return_value=([item(999)], None)
            ), patch(
                "rss_service.pipeline.write_feed", side_effect=OSError("disk full")
            ):
                self.assertTrue(pipeline.build(output, "https://example.com"))
            after = json.loads((output / "state.json").read_text())["ai-utilize"]
            for field in (
                "items",
                "body_collection",
                "published_count",
                "last_success",
                "last_new",
            ):
                self.assertEqual(before[field], after[field])
            self.assertEqual(xml, (output / "feeds/ai-utilize.xml").read_bytes())


class FetchTests(Offline):
    def response(self, data=b'<div class="write_div">Text</div>', status=200):
        response = Mock(status_code=status, headers={"Content-Type": "text/html"})
        response.iter_content.return_value = [data]
        return response

    def test_one_bounded_request_no_redirects_or_media(self):
        with patch("rss_service.http.requests.get") as get:
            get.return_value.__enter__.return_value = self.response()
            self.assertIn(b"write_div", http.fetch_article(URL))
        get.assert_called_once()
        self.assertFalse(get.call_args.kwargs["allow_redirects"])
        self.assertTrue(get.call_args.kwargs["stream"])
        self.assertEqual(get.call_args.kwargs["timeout"], (5, 10))

    def test_invalid_target_does_not_make_request(self):
        for url in (
            "http://127.0.0.1/",
            "https://gall.dcinside.com.evil.test/board/view/?id=x&no=1",
            "https://user:pass@gall.dcinside.com/board/view/?id=x&no=1",
            "https://gall.dcinside.com:8443/board/view/?id=x&no=1",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                http.fetch_article(url)

    def test_redirect_wrong_type_empty_and_size_limit_fail(self):
        for response in (
            self.response(status=302),
            self.response(data=b""),
            self.response(data=b"x" * 11),
        ):
            with patch("rss_service.http.requests.get") as get, patch(
                "rss_service.http.MAX_ARTICLE_BYTES", 10
            ):
                get.return_value.__enter__.return_value = response
                with self.assertRaises(ValueError):
                    http.fetch_article(URL)
        response = self.response()
        response.headers = {"Content-Type": "application/pdf"}
        with patch("rss_service.http.requests.get") as get:
            get.return_value.__enter__.return_value = response
            with self.assertRaises(ValueError):
                http.fetch_article(URL)


if __name__ == "__main__":
    unittest.main()
