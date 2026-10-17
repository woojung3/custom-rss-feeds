import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import requests

from rss_service.pipeline import build, is_transient, update_alert


class AlertTests(unittest.TestCase):
    def test_transport_classification(self):
        for status in (403, 404, 429, 500, 503):
            response = requests.Response()
            response.status_code = status
            self.assertEqual(
                is_transient(requests.HTTPError(response=response)),
                status in (429, 500, 503),
            )
        for exc in (requests.Timeout(), requests.ConnectionError()):
            self.assertTrue(is_transient(exc))
        for exc in (ValueError(), OSError(), requests.HTTPError()):
            self.assertFalse(is_transient(exc))

    def test_both_thresholds_and_recovery(self):
        record = {"last_success": "2026-10-17T00:00:00+00:00", "error": "503"}
        for hour, expected in ((1, False), (2, False), (2, False), (3, True)):
            self.assertEqual(
                update_alert(record, f"2026-10-17T0{hour}:00:00+00:00", True),
                expected,
            )
        record["error"] = None
        self.assertFalse(update_alert(record, "2026-10-17T04:00:00+00:00", False))
        self.assertEqual(record["consecutive_failures"], 0)
        self.assertIsNone(record["first_failure"])
        record["error"] = "503"
        self.assertFalse(update_alert(record, "2026-10-17T08:00:00+00:00", True))

    def test_elapsed_time_alone_does_not_alert(self):
        record = {"last_success": "2026-10-16T00:00:00+00:00", "error": "503"}
        for hour, expected in ((0, False), (1, False), (2, True)):
            self.assertEqual(
                update_alert(record, f"2026-10-17T0{hour}:00:00+00:00", True),
                expected,
            )

    def test_no_success_uses_first_failure(self):
        record = {"error": "timeout"}
        for hour, expected in ((0, False), (2, False), (3, True)):
            self.assertEqual(
                update_alert(record, f"2026-10-17T0{hour}:00:00+00:00", True),
                expected,
            )

    def test_nontransient_is_immediate(self):
        self.assertTrue(
            update_alert({"error": "parser"}, "2026-10-17T00:00:00+00:00", False)
        )

    def test_streak_persists_across_builds_and_preserves_xml(self):
        source = json.loads(Path("sources.json").read_text())[0]
        item = {
            "id": "https://example.com/1",
            "link": "https://example.com/1",
            "title": "test",
            "date": None,
            "summary": "",
        }
        with tempfile.TemporaryDirectory() as tmp, patch(
            "requests.get", side_effect=AssertionError("network in offline test")
        ), patch("rss_service.pipeline.enrich", return_value=None), patch(
            "rss_service.pipeline.datetime"
        ) as clock:
            output = Path(tmp)
            clock.fromisoformat = datetime.fromisoformat
            clock.now.return_value = datetime(2026, 10, 17, tzinfo=timezone.utc)
            with patch("rss_service.pipeline.collect", return_value=([item], None)):
                self.assertFalse(build(output, "https://example.com"))
            original = (output / "feeds" / f"{source['id']}.xml").read_bytes()
            for hour in (1, 2, 3):
                clock.now.return_value = datetime(
                    2026, 10, 17, hour, tzinfo=timezone.utc
                )
                with patch(
                    "rss_service.pipeline.collect",
                    side_effect=requests.Timeout("timeout"),
                ):
                    self.assertEqual(build(output, "https://example.com"), hour == 3)
                saved = json.loads((output / "state.json").read_text())[source["id"]]
                self.assertEqual(saved["consecutive_failures"], hour)
                self.assertEqual(saved["alert_required"], hour == 3)
                self.assertEqual(
                    (output / "feeds" / f"{source['id']}.xml").read_bytes(), original
                )
            with patch("rss_service.pipeline.collect", return_value=([item], None)):
                self.assertFalse(build(output, "https://example.com"))
            saved = json.loads((output / "status.json").read_text())["feeds"][0]
            self.assertEqual(saved["consecutive_failures"], 0)
            self.assertIsNone(saved["error"])
