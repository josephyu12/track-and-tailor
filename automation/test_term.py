#!/usr/bin/env python3
"""Summer 2027 term filter."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from term import evaluate_listing_term, evaluate_term  # noqa: E402


class Summer2027Term(unittest.TestCase):
    def test_named_summer_2027_kept(self) -> None:
        t = evaluate_term("Software Engineer Intern - Summer 2027")
        self.assertTrue(t.ok, t.reason)
        self.assertTrue(t.summer_2027)

    def test_listing_terms_kept(self) -> None:
        t = evaluate_listing_term({"title": "SWE Intern", "terms": ["Summer 2027"]})
        self.assertTrue(t.ok, t.reason)

    def test_summer_and_fall_kept(self) -> None:
        t = evaluate_term(
            "Intern",
            "Roles available Summer 2027 and Fall 2027.",
        )
        self.assertTrue(t.ok, t.reason)

    def test_may_august_2027_kept(self) -> None:
        t = evaluate_term(
            "SWE Intern",
            "Internship runs May 26, 2027 through August 14, 2027.",
        )
        self.assertTrue(t.ok, t.reason)

    def test_june_to_september_2027_kept(self) -> None:
        t = evaluate_term("Intern", "June 2027 to September 2027.")
        self.assertTrue(t.ok, t.reason)

    def test_starts_june_2027_kept(self) -> None:
        t = evaluate_term("Intern", "Start date: June 2, 2027. 12-week program.")
        self.assertTrue(t.ok, t.reason)

    def test_may_through_december_includes_summer(self) -> None:
        t = evaluate_term("Co-op", "Program dates: May 2027 through December 2027.")
        self.assertTrue(t.ok, t.reason)

    def test_fall_2026_only_skipped(self) -> None:
        t = evaluate_term("Fall 2026 Software Engineer Intern", "12 weeks starting September 2026.")
        self.assertFalse(t.ok, t.reason)

    def test_spring_2027_only_skipped(self) -> None:
        t = evaluate_term("Spring 2027 Intern", "January 2027 - April 2027.")
        self.assertFalse(t.ok, t.reason)

    def test_winter_only_skipped(self) -> None:
        t = evaluate_term("Winter 2027 Co-op")
        self.assertFalse(t.ok, t.reason)

    def test_summer_2026_skipped(self) -> None:
        t = evaluate_term("Summer 2026 Software Engineer Intern")
        self.assertFalse(t.ok, t.reason)

    def test_fall_2027_only_skipped(self) -> None:
        t = evaluate_term("Intern", "This is a Fall 2027 internship, September through December.")
        self.assertFalse(t.ok, t.reason)

    def test_jan_april_range_skipped(self) -> None:
        t = evaluate_term("Co-op", "January 2027 to April 2027.")
        self.assertFalse(t.ok, t.reason)

    def test_jd_fall_only_overrides_listing_tag(self) -> None:
        t = evaluate_listing_term(
            {"title": "SWE Intern", "terms": ["Summer 2027"]},
            jd="This role is for Fall 2026 only. September 2026 - December 2026.",
        )
        self.assertFalse(t.ok, t.reason)

    def test_silent_jd_keeps_listing_tag(self) -> None:
        t = evaluate_listing_term(
            {"title": "SWE Intern", "terms": ["Summer 2027"]},
            jd="Write Python backend services and APIs on AWS.",
        )
        self.assertTrue(t.ok, t.reason)

    def test_no_dates_kept(self) -> None:
        t = evaluate_term("Software Engineer Intern", "Write Python and Java. Build APIs.")
        self.assertTrue(t.ok, t.reason)

    def test_undated_summer_intern_kept(self) -> None:
        t = evaluate_term("Summer Intern", "Software engineering internship.")
        self.assertTrue(t.ok, t.reason)

    def test_deadline_january_not_a_term(self) -> None:
        t = evaluate_term(
            "Software Engineer Intern - Summer 2027",
            "Apply by January 15, 2027. Internship is Summer 2027.",
        )
        self.assertTrue(t.ok, t.reason)

    def test_graduation_season_does_not_skip_tagged_summer(self) -> None:
        t = evaluate_listing_term(
            {"title": "Software Engineer Intern", "terms": ["Summer 2027"]},
            jd=(
                "Must be graduating Spring 2028. Write Python backend services. "
                "Expected graduation date May 2028."
            ),
        )
        self.assertTrue(t.ok, t.reason)


if __name__ == "__main__":
    unittest.main()
