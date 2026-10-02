"""US-only location filter for scraped applications."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from daily_run import matches  # noqa: E402
from place import location_kind, outside_us, posting_outside_us  # noqa: E402


class LocationKind(unittest.TestCase):
    def test_us_offices(self) -> None:
        for loc in (
            "New York, NY",
            "Santa Clara, CA",
            "Indianapolis, IN",
            "Seattle, WA",
            "Dallas. TX",
            "Long Island, New York",
            "National Harbor, Maryland",
            "NYC",
            "SF",
            "South SF",
            "Remote in US",
            "U.S. Virgin Islands",
            "Cambridge, MA",
        ):
            self.assertEqual(location_kind(loc), "us", loc)

    def test_other_countries(self) -> None:
        for loc in (
            "Toronto, ON, Canada",
            "London, ON, Canada",
            "Vancouver, BC, Canada",
            "Remote in Canada",
            "Canada",
            "Toronto, ON, CAN",
            "London, UK",
            "Cambridge, UK",
            "United Kingdom",
            "Paris, France",
            "Berlin, Germany",
            "Remote in UK",
            "Chennai, Tamil Nadu, India",
            "Dublin, Ireland",
            "Dubai - United Arab Emirates",
            "Europe",
        ):
            self.assertEqual(location_kind(loc), "foreign", loc)

    def test_unknown_stays(self) -> None:
        for loc in ("Remote", "Hybrid", "Boston", ""):
            self.assertEqual(location_kind(loc), "unknown", loc)


class OutsideUS(unittest.TestCase):
    def test_canada_only_is_outside(self) -> None:
        self.assertTrue(outside_us(["Toronto, ON, Canada"]))
        self.assertTrue(outside_us(["Ottawa, ON, Canada", "Montreal, QC, Canada"]))

    def test_us_or_mixed_is_kept(self) -> None:
        self.assertFalse(outside_us(["New York, NY"]))
        self.assertFalse(outside_us(["Toronto, ON, Canada", "Santa Clara, CA"]))
        self.assertFalse(outside_us(["Remote"]))
        self.assertFalse(outside_us([]))
        self.assertFalse(outside_us(["Remote in USA", "Remote in Canada"]))

    def test_watcher_match_drops_foreign_only(self) -> None:
        cfg = {
            "categories": ["Software"],
            "require_term": "Summer 2027",
            "title_exclude": [],
        }
        base = {
            "active": True,
            "is_visible": True,
            "category": "Software",
            "terms": ["Summer 2027"],
            "title": "SWE Intern",
            "url": "https://example.com/j",
            "degrees": ["Bachelor's"],
        }
        self.assertFalse(matches({**base, "locations": ["Toronto, ON, Canada"]}, cfg))
        self.assertTrue(matches({**base, "locations": ["New York, NY"]}, cfg))
        self.assertTrue(
            matches({**base, "locations": ["Toronto, ON, Canada", "Santa Clara, CA"]}, cfg)
        )
        self.assertTrue(matches({**base, "locations": ["Remote"]}, cfg))

    def test_scraped_city_overrides_generic_remote(self) -> None:
        self.assertTrue(posting_outside_us(["Remote"], "Toronto, ON, Canada"))
        self.assertFalse(posting_outside_us(["Santa Clara, CA"], "Toronto, ON, Canada"))
        self.assertFalse(posting_outside_us(["Remote"], ""))
        self.assertFalse(posting_outside_us([], ""))
