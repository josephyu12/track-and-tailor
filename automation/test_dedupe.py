#!/usr/bin/env python3
"""Duplicate-job identity tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dedupe import DuplicateIndex, collapse_rows, same_job, titles_equivalent  # noqa: E402


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

    def test_swe_and_swe_ml_are_different_jobs(self) -> None:
        self.assertFalse(
            titles_equivalent(
                "Software Engineer Intern",
                "Software Engineer Intern - Machine Learning",
            )
        )
        self.assertFalse(
            same_job(
                "Acme",
                "Software Engineer Intern",
                "https://example.com/swe",
                "Acme",
                "Software Engineer Intern - AI",
                "https://example.com/swe-ai",
            )
        )

    def test_zipline_custom_matches_watcher(self) -> None:
        self.assertTrue(
            titles_equivalent(
                "Software Systems Validation Intern (Summer 2027)",
                "Software Systems Validation Intern (Summer 2027)",
            )
        )

    def test_exact_url_same_string_matches(self) -> None:
        idx = DuplicateIndex()
        url = "https://boards.greenhouse.io/acme/jobs/123"
        idx.add("Acme", "SWE Intern", url, "acme-swe")
        self.assertEqual(idx.match_exact_url(url), "acme-swe")
        self.assertEqual(idx.match("OtherCo", "Other Role", url), "acme-swe")

    def test_tracking_query_and_trailing_slash_still_match(self) -> None:
        idx = DuplicateIndex()
        idx.add("Acme", "SWE Intern", "https://example.com/jobs/1", "acme-swe")
        self.assertEqual(
            idx.match_exact_url("https://example.com/jobs/1?utm_source=Simplify"),
            "acme-swe",
        )
        self.assertEqual(idx.match_exact_url("https://example.com/jobs/1/"), "acme-swe")
        self.assertIsNone(idx.match_exact_url("https://example.com/jobs/2"))

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

    def test_amex_simplify_query_is_same_job(self) -> None:
        self.assertTrue(
            same_job(
                "American Express",
                "Campus Undergraduate Summer Internship Program - 2027 AI Engineer, "
                "Enterprise Technology Services- New York, NY",
                "https://egug.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/26011698?utm_source=Simplify&ref=Simplify",
                "American Express",
                "2027 AI Engineer, Enterprise Technology Services- New York, NY",
                "https://egug.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/26011698",
            )
        )

    def test_collapse_prefers_role_title_over_program_name(self) -> None:
        rows = collapse_rows(
            [
                {
                    "company": "American Express",
                    "title": (
                        "Campus Undergraduate Summer Internship Program - 2027 AI Engineer, "
                        "Enterprise Technology Services- New York, NY"
                    ),
                    "url": "https://egug.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/26011698?utm_source=Simplify&ref=Simplify",
                    "slug": "2027-ai-engineer-enterprise-technology-services-new-york-ny-campus-under",
                    "applied": False,
                    "pdf": False,
                    "keep": True,
                    "fit": {"ok": False, "score": 0.0},
                    "location": "New York, NY",
                },
                {
                    "company": "American Express",
                    "title": "2027 AI Engineer, Enterprise Technology Services- New York, NY",
                    "url": "https://egug.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/26011698",
                    "slug": "american-express-2027-ai-engineer-enterprise-technology-services-new-yor",
                    "applied": False,
                    "pdf": False,
                    "keep": True,
                    "fit": {"ok": True, "score": 0.88},
                    "location": "New York, NY",
                },
            ]
        )
        self.assertEqual(len(rows), 1)
        self.assertIn("AI Engineer", rows[0]["title"])
        self.assertNotIn("Internship Program", rows[0]["title"])
        self.assertGreaterEqual((rows[0].get("fit") or {}).get("score") or 0, 0.40)

    def test_folder_without_pdf_is_not_a_duplicate_when_required(self) -> None:
        import tempfile

        from dedupe import index_from_applications

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        apps = Path(tmp.name)
        folder = apps / "acme-swe"
        folder.mkdir()
        (folder / "job.md").write_text(
            "# Acme — SWE Intern\n\n- Source: https://example.com/jobs/1\n",
            encoding="utf-8",
        )
        idx_all = index_from_applications(apps)
        idx_pdf = index_from_applications(apps, require_pdf=True)
        self.assertEqual(idx_all.match_exact_url("https://example.com/jobs/1"), "acme-swe")
        self.assertIsNone(idx_pdf.match_exact_url("https://example.com/jobs/1"))
        (folder / "resume.pdf").write_bytes(b"%PDF")
        idx_pdf = index_from_applications(apps, require_pdf=True)
        self.assertEqual(idx_pdf.match_exact_url("https://example.com/jobs/1"), "acme-swe")


if __name__ == "__main__":
    unittest.main()
