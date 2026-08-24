#!/usr/bin/env python3
"""Regression tests: truncated HTTP must not crash scrape_one / fetch."""

from __future__ import annotations

import json
import sys
import unittest
from http.client import IncompleteRead
from pathlib import Path
from unittest.mock import MagicMock, patch

SCRAPE_DIR = Path(__file__).resolve().parents[1] / ".cursor" / "skills" / "tailor-resume" / "scripts"
sys.path.insert(0, str(SCRAPE_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from scrape_jd import fetch, scrape_one  # noqa: E402


class FetchResilience(unittest.TestCase):
    def test_incomplete_read_retries_then_uses_partial(self) -> None:
        partial = b"<html><body>" + (b"job description " * 400) + b"</body></html>"
        calls = {"n": 0}

        def boom(*_a, **_k):
            calls["n"] += 1
            raise IncompleteRead(partial)

        with patch("scrape_jd.time.sleep"):
            with patch("scrape_jd._fetch_once", side_effect=boom):
                final, ctype, data = fetch("https://example.com/job", attempts=3, pause=0)

        self.assertEqual(calls["n"], 3)
        self.assertTrue(data.startswith(b"<html>"))
        self.assertGreaterEqual(len(data), 4096)
        self.assertEqual(ctype, "text/html")
        self.assertIn("example.com", final)

    def test_incomplete_read_tiny_partial_raises(self) -> None:
        with patch("scrape_jd.time.sleep"):
            with patch("scrape_jd._fetch_once", side_effect=IncompleteRead(b"nope")):
                with self.assertRaises(IncompleteRead):
                    fetch("https://example.com/job", attempts=2, pause=0)

    def test_scrape_one_never_raises_on_incomplete_read(self) -> None:
        with patch("scrape_jd.time.sleep"):
            with patch("scrape_jd._fetch_once", side_effect=IncompleteRead(b"x")):
                out = scrape_one("https://lifeattiktok.com/search/1")
        self.assertIsInstance(out, dict)
        self.assertIn("ok", out)
        self.assertFalse(out["ok"])
        self.assertIn("IncompleteRead", str(out.get("error") or ""))

    def test_scrape_one_uses_partial_html(self) -> None:
        html = (
            "<html><head><title>SWE Intern | TikTok</title></head>"
            "<body><main>" + ("Build recommendation infrastructure. " * 200) + "</main></body></html>"
        ).encode()

        with patch("scrape_jd.time.sleep"):
            with patch("scrape_jd._fetch_once", side_effect=IncompleteRead(html)):
                out = scrape_one("https://lifeattiktok.com/search/1")
        self.assertTrue(out.get("ok"), msg=json.dumps({k: out.get(k) for k in ("ok", "error", "role")}))
        self.assertIn("recommendation", (out.get("jd_text") or "").lower())


if __name__ == "__main__":
    unittest.main()
