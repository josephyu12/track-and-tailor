#!/usr/bin/env python3
"""Fit-threshold tests. Inline JDs so cleanup of old application folders cannot 404 them."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fit import evaluate_fit  # noqa: E402


class FitThreshold(unittest.TestCase):
    def test_pimco_trading_analyst_skipped(self) -> None:
        fit = evaluate_fit(
            "Trading Analyst Intern",
            "Support the trading desk with Bloomberg and financial modeling.",
            "Quant",
        )
        self.assertFalse(fit.ok, fit.reason)
        self.assertLess(fit.score, 0.2)

    def test_fifth_third_swe_kept(self) -> None:
        fit = evaluate_fit(
            "Software Engineer Co-op - Enterprise Finance Applications - Summer 2027",
            "Write Python and Java backend services. Build APIs on AWS.",
            "Software",
        )
        self.assertTrue(fit.ok, fit.reason)

    def test_general_matter_swe_kept(self) -> None:
        fit = evaluate_fit(
            "Software Engineering Intern",
            "Software engineers write code in Python and C++.",
            "Software",
        )
        self.assertTrue(fit.ok, fit.reason)

    def test_fannie_data_science_kept(self) -> None:
        fit = evaluate_fit(
            "Data Science Intern - Analytics & Modeling Program",
            "Python, SQL, machine learning, AWS, Jupyter, pandas.",
            "AI/ML/Data",
        )
        self.assertTrue(fit.ok, fit.reason)

    def test_zipline_perception_skipped(self) -> None:
        fit = evaluate_fit(
            "Perception Intern - Summer 2027",
            "Computer vision, SLAM, lidar, robotics, PyTorch on drones.",
            "AI/ML/Data",
        )
        self.assertFalse(fit.ok, fit.reason)

    def test_research_scientist_cv_ml_kept(self) -> None:
        fit = evaluate_fit(
            "Research Scientist",
            "Machine learning, computer vision, digital signal processing, "
            "algorithms, linear algebra, scientific computing, Python.",
            "custom",
            company="Anduril Industries",
        )
        self.assertTrue(fit.ok, fit.reason)
        self.assertGreaterEqual(fit.score, 0.40)

    def test_ml_engineer_title_kept(self) -> None:
        fit = evaluate_fit(
            "Machine Learning Engineer Intern",
            "Train PyTorch models, ship Python services on AWS Kubernetes.",
            "AI/ML/Data",
        )
        self.assertTrue(fit.ok, fit.reason)

    def test_mechanical_skipped(self) -> None:
        fit = evaluate_fit("Mechanical Engineer Intern", "CAD and SolidWorks.", "Hardware")
        self.assertFalse(fit.ok)

    def test_ai_engineer_title_kept(self) -> None:
        fit = evaluate_fit(
            "2027 AI Engineer, Enterprise Technology Services- New York, NY",
            "",
            "custom",
        )
        self.assertTrue(fit.ok, fit.reason)
        self.assertGreaterEqual(fit.score, 0.40)

    def test_amex_program_prefix_heading_kept(self) -> None:
        from fit import evaluate_job_md

        text = (
            "# American Express — Campus Undergraduate Summer Internship Program - "
            "2027 AI Engineer, Enterprise Technology Services- New York, NY\n\n"
            "- Category: custom\n\n"
            "## Job description\n\n"
            "As an AI Engineer Intern you will write Python, train machine learning "
            "models, and ship APIs on AWS.\n"
        )
        fit = evaluate_job_md(text)
        self.assertTrue(fit.ok, fit.reason)
        self.assertGreaterEqual(fit.score, 0.40)

    def test_swapped_program_and_role_still_kept(self) -> None:
        fit = evaluate_fit(
            "Campus Undergraduate Summer Internship Program",
            "",
            "custom",
            company="2027 AI Engineer, Enterprise Technology Services- New York, NY",
        )
        self.assertTrue(fit.ok, fit.reason)
        self.assertGreaterEqual(fit.score, 0.40)

    def test_program_name_alone_skipped(self) -> None:
        fit = evaluate_fit("Campus Undergraduate Summer Internship Program")
        self.assertFalse(fit.ok, fit.reason)

    def test_listing_uses_company_when_title_swapped(self) -> None:
        from fit import evaluate_listing

        fit = evaluate_listing(
            {
                "title": "Campus Undergraduate Summer Internship Program",
                "company_name": "2027 AI Engineer, Enterprise Technology Services",
                "category": "custom",
            }
        )
        self.assertTrue(fit.ok, fit.reason)

    def test_write_and_backfill_fit_json(self) -> None:
        import tempfile

        from fit import backfill_missing_fits, evaluate_job_md, write_fit_json

        text = (
            "# Acme — Software Engineer Intern\n\n"
            "- Category: Software\n\n"
            "## Job description\n\n"
            "Write Python backend services and APIs on AWS.\n\n"
            "## Application questions\n\n"
            "None found\n"
        )
        fit = evaluate_job_md(text)
        self.assertTrue(fit.ok, fit.reason)
        with tempfile.TemporaryDirectory() as tmp:
            apps = Path(tmp)
            missing = apps / "acme-swe"
            missing.mkdir()
            (missing / "job.md").write_text(text, encoding="utf-8")
            already = apps / "kept"
            already.mkdir()
            (already / "job.md").write_text(text, encoding="utf-8")
            write_fit_json(already, fit, extra={"custom": True})
            wrote = backfill_missing_fits(apps)
            self.assertEqual(wrote, 1)
            payload = json.loads((missing / "fit.json").read_text(encoding="utf-8"))
            self.assertAlmostEqual(payload["score"], fit.score)
            kept = json.loads((already / "fit.json").read_text(encoding="utf-8"))
            self.assertTrue(kept["custom"])

    def test_sync_overwrites_stale_zero_fit(self) -> None:
        import tempfile

        from fit import sync_fit_json

        text = (
            "# American Express — Campus Undergraduate Summer Internship Program - "
            "2027 AI Engineer, Enterprise Technology Services- New York, NY\n\n"
            "- Category: custom\n\n"
            "## Job description\n\n"
            "Python machine learning models, LLM APIs, and backend services on AWS.\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "amex-ai"
            folder.mkdir()
            (folder / "job.md").write_text(text, encoding="utf-8")
            (folder / "fit.json").write_text(
                json.dumps(
                    {
                        "ok": False,
                        "score": 0.0,
                        "reason": "not a strong fit — title is not SWE/ML/data "
                        "(score 0.00, need 0.40)",
                        "custom": True,
                    }
                ),
                encoding="utf-8",
            )
            self.assertTrue(sync_fit_json(folder))
            payload = json.loads((folder / "fit.json").read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"], payload["reason"])
            self.assertGreaterEqual(payload["score"], 0.40)
            self.assertTrue(payload["custom"])


if __name__ == "__main__":
    unittest.main()
