#!/usr/bin/env python3
"""Start Application CTA + apply-form harvest helpers (no live browser)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRAPE_DIR = Path(__file__).resolve().parents[1] / ".cursor" / "skills" / "tailor-resume" / "scripts"
sys.path.insert(0, str(SCRAPE_DIR))

from application_questions import (  # noqa: E402
    extract_questions_from_html,
    find_apply_hrefs,
    is_apply_cta,
    questions_from_forms_json,
    questions_look_real,
)
from scrape_jd import harvest_apply_questions, scrape_one  # noqa: E402

LISTING_HTML = """
<html>
  <a href="/jobs/1/apply">Start Application</a>
  <form>
    <label>Email me about similar jobs</label>
    <input type="email" name="job_alert">
    <select aria-label="Site language"><option>English</option></select>
  </form>
</html>
"""

APPLY_HTML = """
<html>
  <form>
    <label>Are you authorized to work in the United States?</label>
    <textarea aria-label="Why do you want this role?"></textarea>
    <input aria-label="First name" name="first_name" required>
  </form>
</html>
"""


class ApplyCta(unittest.TestCase):
    def test_start_application(self) -> None:
        self.assertTrue(is_apply_cta("Start Application"))

    def test_apply_now(self) -> None:
        self.assertTrue(is_apply_cta("Apply Now"))

    def test_apply_manually(self) -> None:
        self.assertTrue(is_apply_cta("Apply Manually"))

    def test_submit_is_not_apply(self) -> None:
        self.assertFalse(is_apply_cta("Submit"))
        self.assertFalse(is_apply_cta("Submit Application"))

    def test_linkedin_autofill_is_not_apply(self) -> None:
        self.assertFalse(is_apply_cta("Apply with LinkedIn"))

    def test_find_start_application_href(self) -> None:
        hrefs = find_apply_hrefs(LISTING_HTML, "https://example.com/jobs/1")
        self.assertIn("https://example.com/jobs/1/apply", hrefs)


class QuestionQuality(unittest.TestCase):
    def test_job_alert_only_is_not_real(self) -> None:
        self.assertFalse(
            questions_look_real(
                [{"prompt": "Email me about similar jobs", "kind": "other", "type": "email"}]
            )
        )

    def test_cookie_only_is_not_real(self) -> None:
        self.assertFalse(
            questions_look_real([{"prompt": "Accept cookies", "kind": "other", "type": "checkbox"}])
        )

    def test_screening_is_real(self) -> None:
        self.assertTrue(
            questions_look_real(
                [
                    {
                        "prompt": "Are you authorized to work in the US?",
                        "kind": "screening",
                        "type": "select",
                    }
                ]
            )
        )

    def test_forms_json_skips_hidden_and_submit(self) -> None:
        qs = questions_from_forms_json(
            [
                {
                    "id": "app",
                    "method": "post",
                    "fields": [
                        {
                            "type": "text",
                            "name": "first_name",
                            "placeholder": "First name",
                            "required": True,
                        },
                        {
                            "type": "textarea",
                            "name": "why",
                            "placeholder": "Why this role?",
                        },
                        {"type": "hidden", "name": "csrf"},
                        {"type": "submit", "name": "commit"},
                        {
                            "type": "select",
                            "name": "auth",
                            "label": "Work authorization",
                            "options": [{"text": "Yes"}, {"text": "No"}],
                        },
                    ],
                }
            ]
        )
        prompts = [q["prompt"] for q in qs]
        self.assertEqual(prompts, ["First name", "Why this role?", "Work authorization"])
        self.assertEqual(qs[2]["options"], ["Yes", "No"])

    def test_html_input_aria_label(self) -> None:
        qs = extract_questions_from_html(
            '<form><input aria-label="Legal first name" name="fn" required>'
            '<textarea aria-label="Why us?"></textarea></form>'
        )
        prompts = {q["prompt"] for q in qs}
        self.assertIn("Legal first name", prompts)
        self.assertIn("Why us?", prompts)


class HarvestFollow(unittest.TestCase):
    def test_follows_start_application_href(self) -> None:
        def fake_fetch(url: str, accept: str = "*/*") -> tuple[str, str]:
            if url.endswith("/apply") or url.endswith("/application"):
                return url, APPLY_HTML
            return url, LISTING_HTML

        with patch("scrape_jd.fetch_text", side_effect=fake_fetch):
            qs = harvest_apply_questions(
                "https://example.com/jobs/1", html=LISTING_HTML
            )
        prompts = {q["prompt"] for q in qs}
        self.assertTrue(questions_look_real(qs))
        self.assertTrue(any("authorized" in p.lower() for p in prompts))
        self.assertTrue(any("why" in p.lower() for p in prompts))

    def test_browser_flag_calls_harvest(self) -> None:
        harvested = {
            "questions": [
                {
                    "prompt": "Are you authorized to work in the US?",
                    "kind": "screening",
                    "type": "select",
                    "required": True,
                    "options": ["Yes", "No"],
                    "name": "",
                    "description": "",
                }
            ],
            "clicked": "Start Application",
            "login_walled": False,
            "error": None,
        }
        http = {
            "ok": True,
            "url": "https://example.com/jobs/1",
            "company": "Acme",
            "role": "Intern",
            "jd_text": "Python " * 80,
            "questions": [],
            "error": None,
        }
        with patch("scrape_jd._scrape_one", return_value=http):
            with patch(
                "harvest_apply_form.harvest_apply_form", return_value=harvested
            ) as mock_harvest:
                out = scrape_one("https://example.com/jobs/1", browser=True)
        mock_harvest.assert_called_once()
        self.assertEqual(out["apply_clicked"], "Start Application")
        self.assertTrue(questions_look_real(out.get("questions")))

    def test_browser_off_skips_harvest(self) -> None:
        http = {
            "ok": True,
            "url": "https://example.com/jobs/1",
            "company": "Acme",
            "role": "Intern",
            "jd_text": "Python " * 80,
            "questions": [],
            "error": None,
        }
        with patch("scrape_jd._scrape_one", return_value=http):
            with patch("harvest_apply_form.harvest_apply_form") as mock_harvest:
                out = scrape_one("https://example.com/jobs/1", browser=False)
        mock_harvest.assert_not_called()
        self.assertEqual(out.get("questions"), [])


class HarvestStaysHeadless(unittest.TestCase):
    def test_headed_status(self) -> None:
        from harvest_apply_form import is_headed_status

        self.assertTrue(is_headed_status("Status: healthy\nMode: headed\nURL: https://x"))
        self.assertFalse(is_headed_status("Status: healthy\nMode: launched\nURL: https://x"))
        self.assertFalse(is_headed_status(""))

    def test_ensure_headless_disconnects_headed_daemon(self) -> None:
        from harvest_apply_form import ensure_headless

        calls: list[list[str]] = []

        def fake_run(args, timeout=45):
            calls.append(list(args))
            if args[:1] == ["status"]:
                return 0, "Status: healthy\nMode: headed\nURL: https://x"
            return 0, "ok"

        with patch("harvest_apply_form.run_browse", side_effect=fake_run):
            ensure_headless()
        self.assertEqual(calls, [["status"], ["disconnect"]])

    def test_ensure_headless_skips_disconnect_when_already_headless(self) -> None:
        from harvest_apply_form import ensure_headless

        calls: list[list[str]] = []

        def fake_run(args, timeout=45):
            calls.append(list(args))
            return 0, "Status: healthy\nMode: launched"

        with patch("harvest_apply_form.run_browse", side_effect=fake_run):
            ensure_headless()
        self.assertEqual(calls, [["status"]])


if __name__ == "__main__":
    unittest.main()
