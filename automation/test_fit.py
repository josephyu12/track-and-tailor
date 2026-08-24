#!/usr/bin/env python3
"""Fit-threshold tests. Inline JDs so cleanup of old application folders cannot 404 them."""

from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
