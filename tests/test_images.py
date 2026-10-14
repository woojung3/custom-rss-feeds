import json
from pathlib import Path
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from rss_service.images import (
    miniflux_rewrite_rules,
    normalize_dc_image_url,
    normalize_dc_images,
)
from rss_service.rendering import write_feed, CONTENT_NS


class ImageTests(unittest.TestCase):
    def test_both_host_families_and_routes_keep_raw_query(self):
        for host in ("dcimg6.dcinside.co.kr", "dcimg5.dcinside.com"):
            for path in ("viewimage.php", "dccon.php"):
                for scheme in ("http", "https"):
                    query = "id=a%2Fb&no=xyz%2B12&orgExt=&no=second"
                    url = f"{scheme}://{host}/{path}?{query}#fragment"
                    with self.subTest(url=url):
                        expected = f"https://image.dcinside.com/{path}?{query}#fragment"
                        self.assertEqual(normalize_dc_image_url(url), expected)
                        self.assertEqual(normalize_dc_image_url(expected), expected)

    def test_unknown_routes_domains_and_credentials_untouched(self):
        urls = (
            "https://gall.dcinside.com/board/view/?id=x&no=1",
            "https://dcimg6.dcinside.co.kr/viewimagePop.php?id=x&no=1",
            "https://dcimg6.dcinside.co.kr/other.php?id=x",
            "https://dcimg6.dcinside.co.kr.evil.test/viewimage.php?id=x",
            "https://user:pass@dcimg6.dcinside.co.kr/viewimage.php?id=x",
            "https://dcimg6.dcinside.co.kr:8443/viewimage.php?id=x",
            "https://dcimg6.dcinside.co.kr/viewimage.php",
            "https://example.com/viewimage.php?id=x",
            "javascript:alert(1)",
        )
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(normalize_dc_image_url(url), url)

    def test_only_img_sources_change_not_links_or_quoted_text(self):
        url = "https://dcimg6.dcinside.co.kr/viewimage.php?id=x&no=1"
        escaped = url.replace("&", "&amp;")
        source = f'<p>{escaped}</p><a href="{escaped}">link</a><img src="{escaped}">'
        result = normalize_dc_images(source)
        soup = BeautifulSoup(result, "html.parser")
        self.assertEqual(soup.p.get_text(), url)
        self.assertEqual(soup.a["href"], url)
        self.assertEqual(
            soup.img["src"], url.replace("dcimg6.dcinside.co.kr", "image.dcinside.com")
        )
        self.assertEqual(normalize_dc_images(result), result)

    def test_unrelated_markup_unchanged_byte_for_byte(self):
        source = (
            '<p>Body\n  text</p><img alt="example" src="https://example.com/image.png">'
        )
        self.assertEqual(normalize_dc_images(source), source)

    def test_cached_body_is_normalized_on_render_without_mutating_state(self):
        old = '<p>Original</p><img src="https://dcimg6.dcinside.co.kr/viewimage.php?id=x&amp;no=1">'
        item = {
            "id": "https://gall.dcinside.com/board/view/?id=x&no=1",
            "link": "https://gall.dcinside.com/board/view/?id=x&no=1",
            "title": "Example",
            "date": "2026-10-14T00:00:00+00:00",
            "summary": "Original",
            "content_html": old,
        }
        source = {
            "id": "ai-utilize",
            "name": "Example",
            "emoji": "X",
            "kind": "dc",
            "url": "https://example.com/",
            "article_content": True,
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "feed.xml"
            write_feed(output, source, [item], item["date"], "https://example.com")
            node = ET.parse(output).find("./channel/item")
            self.assertIn(
                "image.dcinside.com/viewimage.php",
                node.findtext(f"{{{CONTENT_NS}}}encoded"),
            )
            self.assertEqual(node.findtext("guid"), item["id"])
            self.assertEqual(item["content_html"], old)
            write_feed(
                output,
                dict(source, article_content=False),
                [item],
                item["date"],
                "https://example.com",
            )
            self.assertEqual(
                ET.parse(output).findtext(f"./channel/item/{{{CONTENT_NS}}}encoded"),
                old,
            )

    def test_miniflux_recipe_covers_only_known_image_sources(self):
        settings = json.loads(Path("integrations/miniflux-dcinside.json").read_text())
        self.assertEqual(settings["scraper_rules"], ".write_div")
        self.assertEqual(set(settings), {"scraper_rules", "rewrite_rules"})
        self.assertEqual(settings["rewrite_rules"], miniflux_rewrite_rules())
        tokens = re.findall(
            r'replace\(("(?:[^"\\]|\\.)*")\|("(?:[^"\\]|\\.)*")\)',
            settings["rewrite_rules"],
        )
        self.assertEqual(len(tokens), 4)
        self.assertEqual(
            "add_dynamic_image," + ",".join(f"replace({a}|{b})" for a, b in tokens),
            settings["rewrite_rules"],
        )
        # Miniflux first unquotes string tokens, THEN compiles the regex. These
        # generated ASCII JSON strings use the compatible Go escaping subset.
        rules = [(json.loads(a), json.loads(b)) for a, b in tokens]
        for pattern, _ in rules:
            self.assertTrue(pattern)
            self.assertFalse(re.compile(pattern).match(""))

        # Do not merely test regex text without the string-unquoting layer.
        def rewrite(value):
            for pattern, replacement in rules:
                replacement = replacement.replace("${1}", r"\g<1>")
                value = re.sub(pattern, replacement, value)
            return value

        for host in ("dcimg6.dcinside.co.kr", "dcimg5.dcinside.com"):
            for path in ("viewimage.php", "dccon.php"):
                url = f"https://{host}/{path}?id=x&amp;no=1"
                content = f'<p>{url}</p><a href="{url}">link</a><img alt="example" src="{url}"/>'
                result = rewrite(content)
                self.assertEqual(result.count("https://image.dcinside.com/"), 1)
                self.assertIn(f'<a href="{url}">', result)
                self.assertEqual(rewrite(result), result)
        for url in (
            "https://dcimg6.dcinside.co.kr/other.php?id=x",
            "https://dcimg6.dcinside.co.kr.evil.test/viewimage.php?id=x",
        ):
            content = f'<img src="{url}"/>'
            self.assertEqual(rewrite(content), content)
        self.assertEqual(
            rewrite(
                '<img data-src="https://dcimg6.dcinside.co.kr/viewimage.php?id=x"/>'
            ),
            '<img data-src="https://dcimg6.dcinside.co.kr/viewimage.php?id=x"/>',
        )


if __name__ == "__main__":
    unittest.main()
