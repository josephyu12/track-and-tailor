#!/usr/bin/env python3
"""Duplicate-job identity tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dedupe import collapse_rows, same_job, titles_equivalent  # noqa: E402


class Dedupe(unittest.TestCase):
    def test_amd_swe_locations(self) -> None:
        self.assertTrue(
            same_job(
                "AMD",
                "Software Engineer Intern/Co-op",
                "https://careers.amd.com/jobs/90891?icims=1",
                "AMD",
                "Software Engineer Intern/Co-op",
                "https://careers.amd.com/jobs/90947?icims=1",
            )
        )

    def test_amd_ml_team_suffix(self) -> None:
        self.assertTrue(
            titles_equivalent(
                "Machine Learning Intern/Co-op - Machine Learning - Artificial Intelligence",
                "Machine Learning Intern/Co-op - Multiple Teams",
            )
        )

    def test_vanguard_offices(self) -> None:
        self.assertTrue(
            same_job(
                "Vanguard",
                "Data Science Intern - Information Technology",
                "https://vanguard.wd5.myworkdayjobs.com/en-US/vanguard_external/job/Malvern-PA/College-to-Corporate-IT-Internship---Data-Science--PA-_181766",
                "Vanguard",
                "Data Science Intern - College to Corporate IT",
                "https://vanguard.wd5.myworkdayjobs.com/en-US/vanguard_external/job/Charlotte-NC/College-to-Corporate-IT-Internship---Data-Science--NC-_181765",
            )
        )

    def test_tiktok_different_teams_kept(self) -> None:
        self.assertFalse(
            titles_equivalent(
                "Software Engineer Intern - Recommendation Architecture - Feeds Infrastructure",
                "Software Engineer Intern - TikTok Search Architecture",
            )
        )

    def test_zipline_custom_matches_watcher(self) -> None:
        self.assertTrue(
            titles_equivalent(
                "Software Systems Validation Intern (Summer 2027)",
                "Software Systems Validation Intern (Summer 2027)",
            )
        )

    def test_collapse_prefers_applied(self) -> None:
        rows = collapse_rows(
            [
                {
                    "company": "AMD",
                    "title": "Software Engineer Intern/Co-op",
                    "url": "https://careers.amd.com/jobs/90891",
                    "slug": "amd-software-engineer-intern-co-op",
                    "applied": False,
                    "pdf": True,
                    "keep": False,
                    "location": "Santa Clara, CA",
                },
                {
                    "company": "AMD",
                    "title": "Software Engineer Intern/Co-op",
                    "url": "https://careers.amd.com/jobs/90947",
                    "slug": "amd-software-engineer-intern-co-op-944978fc",
                    "applied": True,
                    "pdf": True,
                    "keep": False,
                    "location": "Austin, TX",
                },
            ]
        )
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["applied"])
        self.assertEqual(rows[0]["dup_count"], 1)


if __name__ == "__main__":
    unittest.main()
