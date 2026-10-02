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
    jd_looks_like_posting,
    parse_html,
    parse_icims,
    parse_oracle,
    scrape_one,
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


POSTING_BODY = (
    "Responsibilities include writing Python services for Jira. "
    "Requirements: currently pursuing a CS degree. "
    "Qualifications: Java or Python. You will ship production code. "
    "Preferred skills: Git, testing, and code review. "
) * 6

ICIMS_JOB = "https://careers-americas.icims.com/jobs/26266/software-engineer-intern/job"
ICIMS_IFRAME = ICIMS_JOB + "?in_iframe=1"
ICIMS_JSONLD = json.dumps(
    {
        "@type": "JobPosting",
        "title": "Software Engineer Intern, 2027 Summer U.S.",
        "hiringOrganization": {"name": "Atlassian"},
        "jobLocation": {
            "address": {"addressLocality": "San Francisco", "addressRegion": "CA"}
        },
        "description": f"<p>{POSTING_BODY}</p>",
    }
)
ICIMS_IFRAME_HTML = (
    "<html><head><title>Software Engineer Intern</title>"
    f'<script type="application/ld+json">{ICIMS_JSONLD}</script></head>'
    f"<body><h1>Software Engineer Intern</h1><p>{POSTING_BODY}</p></body></html>"
)
ICIMS_WRAPPER_HTML = (
    '<html><body><iframe src="' + ICIMS_IFRAME + '"></iframe><main>'
    + (
        "Talent Community. Browse all jobs. Skip to main content. "
        "Employee Login. Featured Careers. Candidate Resources Hub. "
    )
    * 25
    + "</main></body></html>"
)


def _fake_fetch(url: str, accept: str = "*/*", headers=None):
    if "in_iframe=1" in url:
        return url, ICIMS_IFRAME_HTML
    return url, ICIMS_WRAPPER_HTML


class ChromeJd(unittest.TestCase):
    def test_wrapper_copy_is_not_a_posting(self) -> None:
        chrome = (
            "Talent Community. Browse all jobs. Skip to main content. "
            "Employee Login. Featured Careers. Candidate Resources Hub. "
        ) * 20
        self.assertFalse(jd_looks_like_posting(chrome))
        self.assertTrue(jd_looks_like_posting(POSTING_BODY))

    def test_parse_html_rejects_careers_chrome(self) -> None:
        html = "<html><body><main>" + (
            "Talent Community. Browse all jobs. Skip to main content. "
            "Employee Login. Featured Careers. "
        ) * 20 + "</main></body></html>"
        with patch("scrape_jd.fetch_text", return_value=("https://example.com/careers", html)):
            out = parse_html("https://example.com/careers")
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "chrome")

    def test_successfactors_jobdisplay_beats_chrome(self) -> None:
        html = (
            "Skip to main content Language Deutsch (Deutschland) "
            "Employee Login Featured Careers Talent Community "
            '<div class="jobDisplay">'
            '<h1 id="job-title">ML Intern</h1>'
            f'<div class="jobdescription">{POSTING_BODY}</div></div>'
            '<div id="similar-jobs">other roles</div>'
        )
        with patch(
            "scrape_jd.fetch_text",
            return_value=("https://corningjobs.corning.com/job/1", html),
        ):
            out = parse_html("https://corningjobs.corning.com/job/1")
        self.assertTrue(out["ok"], msg=json.dumps({k: out.get(k) for k in ("ok", "error")}))
        self.assertIn("Python", out["jd_text"])
        self.assertNotIn("Deutsch", out["jd_text"])


class IcimsIframe(unittest.TestCase):
    def test_parse_icims_reads_iframe_jsonld(self) -> None:
        with patch("scrape_jd.fetch_text", side_effect=_fake_fetch):
            out = parse_icims(ICIMS_JOB)
        self.assertIsNotNone(out)
        assert out is not None
        self.assertTrue(out["ok"], msg=json.dumps({k: out.get(k) for k in ("ok", "error", "role")}))
        self.assertEqual(out["ats"], "icims")
        self.assertIn("Software Engineer Intern", out["role"])
        self.assertIn("Python", out["jd_text"])
        self.assertNotIn("Talent Community", out["jd_text"])

    def test_scrape_one_does_not_keep_wrapper_chrome(self) -> None:
        with patch("scrape_jd.fetch_text", side_effect=_fake_fetch):
            out = scrape_one(ICIMS_JOB)
        self.assertTrue(out.get("ok"), msg=json.dumps({k: out.get(k) for k in ("ok", "error", "role")}))
        self.assertIn("Python", out.get("jd_text") or "")
        self.assertNotIn("Candidate Resources Hub", out.get("jd_text") or "")

    def test_parse_html_follows_job_iframe(self) -> None:
        with patch("scrape_jd.fetch_text", side_effect=_fake_fetch):
            out = parse_html(ICIMS_JOB)
        self.assertTrue(out["ok"])
        self.assertIn("Python", out["jd_text"])


if __name__ == "__main__":
    unittest.main()
