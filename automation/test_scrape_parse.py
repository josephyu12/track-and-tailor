#!/usr/bin/env python3
"""Headline split + Oracle HCM parser tests (Amex-style campus titles)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRAPE_DIR = Path(__file__).resolve().parents[1] / ".cursor" / "skills" / "tailor-resume" / "scripts"
sys.path.insert(0, str(SCRAPE_DIR))

from scrape_jd import (  # noqa: E402
    company_from_boilerplate,
    parse_oracle,
    split_headline,
)

AMEX_TITLE = (
    "Campus Undergraduate Summer Internship Program - 2027 AI Engineer, "
    "Enterprise Technology Services- New York, NY"
)
AMEX_URL = (
    "https://egug.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/26011698"
)


class HeadlineSplit(unittest.TestCase):
    def test_amex_program_then_role(self) -> None:
        role, company = split_headline(AMEX_TITLE, "American Express")
        self.assertIn("AI Engineer", role)
        self.assertNotIn("Internship Program", role)
        self.assertEqual(company, "American Express")

    def test_amex_without_site_still_keeps_role(self) -> None:
        role, company = split_headline(AMEX_TITLE, "")
        self.assertIn("AI Engineer", role)
        self.assertEqual(company, "")

    def test_role_pipe_company(self) -> None:
        role, company = split_headline("SWE Intern | TikTok")
        self.assertEqual(role, "SWE Intern")
        self.assertEqual(company, "TikTok")

    def test_jpmc_location_suffix(self) -> None:
        role, company = split_headline(
            "Code for Good Hackathon - Software Engineer Program - 2027 Summer Internship – United States",
            "JPMorganChase",
        )
        self.assertIn("Software Engineer", role)
        self.assertEqual(company, "JPMorganChase")
        self.assertNotEqual(company, "United States")

    def test_data_science_keeps_left_role(self) -> None:
        role, company = split_headline(
            "Data Science Intern - Analytics & Modeling Program"
        )
        self.assertEqual(role, "Data Science Intern")


class CompanyBoilerplate(unittest.TestCase):
    def test_at_american_express(self) -> None:
        html = "<p>At American Express, our culture is built on innovation.</p>"
        self.assertEqual(company_from_boilerplate(html), "American Express")

    def test_jpmc_leading_name(self) -> None:
        html = "<p>JPMorganChase, one of the oldest financial institutions, offers solutions.</p>"
        self.assertEqual(company_from_boilerplate(html), "JPMorganChase")


class OracleParser(unittest.TestCase):
    def test_parse_oracle_splits_amex_title(self) -> None:
        payload = {
            "items": [
                {
                    "Title": AMEX_TITLE,
                    "PrimaryLocation": "New York, NY, United States",
                    "WorkplaceType": "Hybrid",
                    "ExternalDescriptionStr": "<p>" + ("Python machine learning models. " * 40) + "</p>",
                    "ExternalResponsibilitiesStr": "<p>Support AI/ML models and LLM integration.</p>",
                    "ExternalQualificationsStr": "<p>Bachelor degree candidates in computer science.</p>",
                    "CorporateDescriptionStr": "<p>At American Express, our culture is built on innovation.</p>",
                    "requisitionFlexFields": [
                        {"Prompt": "Salary Range", "Value": "$24.05 - $63 hourly"}
                    ],
                }
            ]
        }
        with patch("scrape_jd.fetch_json", return_value=("https://api", payload)):
            out = parse_oracle(AMEX_URL)
        self.assertIsNotNone(out)
        assert out is not None
        self.assertTrue(out["ok"], msg=json.dumps({k: out.get(k) for k in ("ok", "error", "role")}))
        self.assertEqual(out["ats"], "oracle")
        self.assertEqual(out["company"], "American Express")
        self.assertIn("AI Engineer", out["role"])
        self.assertNotIn("Internship Program", out["role"])
        self.assertIn("Python", out["jd_text"])
        self.assertIn("LLM", out["jd_text"])
        self.assertIn("New York", out["location"])

    def test_parse_oracle_ignores_non_oracle_urls(self) -> None:
        self.assertIsNone(parse_oracle("https://boards.greenhouse.io/acme/jobs/1"))


if __name__ == "__main__":
    unittest.main()
