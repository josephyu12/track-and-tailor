#!/usr/bin/env python3
"""Agent timeout must kill the whole process group, not hang on grandchild pipes."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from daily_run import kill_tailor_for_slug, run_agent_cmd  # noqa: E402
from test_check_resume import pdf_bytes  # noqa: E402

# Parent + grandchild both sleep. Killing only the parent leaves the grandchild
# holding stdout, which is what made subprocess.run(timeout=) hang for ~1h.
HANG_SCRIPT = r"""
import os, time
if os.fork() == 0:
    while True:
        time.sleep(1)
print("started", flush=True)
while True:
    time.sleep(1)
"""


class AgentTimeout(unittest.TestCase):
    def test_timeout_returns_instead_of_hanging_on_grandchild(self) -> None:
        t0 = time.time()
        code, out, timed_out = run_agent_cmd(
            [sys.executable, "-c", HANG_SCRIPT],
            timeout=1,
            cwd=str(Path(__file__).resolve().parent),
            env=os.environ.copy(),
        )
        elapsed = time.time() - t0
        self.assertTrue(timed_out)
        self.assertLess(elapsed, 12, msg=f"hung {elapsed:.1f}s; process group was not killed")
        self.assertIn("started", out)

    def test_fast_command_is_not_timed_out(self) -> None:
        code, out, timed_out = run_agent_cmd(
            [sys.executable, "-c", "print('ok')"],
            timeout=10,
            cwd=str(Path(__file__).resolve().parent),
            env=os.environ.copy(),
        )
        self.assertFalse(timed_out)
        self.assertEqual(code, 0)
        self.assertIn("ok", out)


class KillTailorOnDelete(unittest.TestCase):
    def test_kill_tailor_for_slug_kills_process_group(self) -> None:
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name) / "acme-swe"
        folder.mkdir()
        t0 = time.time()
        proc = subprocess.Popen(
            [sys.executable, "-c", HANG_SCRIPT],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.addCleanup(lambda: proc.poll() is not None or proc.kill())
        (folder / ".tailor.pid").write_text(str(proc.pid), encoding="utf-8")
        self.assertTrue(kill_tailor_for_slug("acme-swe", folder))
        deadline = time.time() + 3
        while proc.poll() is None and time.time() < deadline:
            time.sleep(0.05)
        self.assertIsNotNone(proc.poll())
        self.assertLess(time.time() - t0, 8)
        self.assertFalse((folder / ".tailor.pid").exists())


class SequentialTailor(unittest.TestCase):
    def test_both_runs_resume_then_answers(self) -> None:
        from unittest.mock import patch

        import daily_run

        calls: list[tuple[bool, bool]] = []

        def fake_phase(slug, listing, timeout, *, do_resume, do_answers, do_cover=False):
            calls.append((do_resume, do_answers, do_cover))
            return True, "ok"

        started = []
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "applications" / "acme-swe").mkdir(parents=True)
        with patch.object(daily_run, "ROOT", root), patch.object(
            daily_run, "_tailor_phase", side_effect=fake_phase
        ):
            ok, detail = daily_run.tailor_with_cursor(
                "acme-swe",
                {"company_name": "Acme", "title": "SWE Intern", "url": "https://ex"},
                timeout=1,
                do_resume=True,
                do_answers=True,
                on_start=lambda: started.append(True),
            )
        self.assertTrue(ok, detail)
        self.assertEqual(calls, [(True, False, False), (False, True, False)])
        self.assertEqual(started, [True])
        self.assertIn("ok", detail)

    def test_resume_failure_skips_answers(self) -> None:
        from unittest.mock import patch

        import daily_run

        calls: list[tuple[bool, bool]] = []

        def fake_phase(slug, listing, timeout, *, do_resume, do_answers, do_cover=False):
            calls.append((do_resume, do_answers, do_cover))
            if do_resume:
                return False, "cursor agent timed out after 600s"
            return True, "should not run"

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "applications" / "acme-swe").mkdir(parents=True)
        with patch.object(daily_run, "ROOT", root), patch.object(
            daily_run, "_tailor_phase", side_effect=fake_phase
        ):
            ok, detail = daily_run.tailor_with_cursor(
                "acme-swe",
                {"company_name": "Acme", "title": "SWE Intern", "url": "https://ex"},
                timeout=1,
                do_resume=True,
                do_answers=True,
            )
        self.assertFalse(ok, detail)
        self.assertEqual(calls, [(True, False, False)])
        self.assertIn("timed out", detail)

    def test_resume_ok_is_success_even_if_answers_fail(self) -> None:
        from unittest.mock import patch

        import daily_run

        def fake_phase(slug, listing, timeout, *, do_resume, do_answers, do_cover=False):
            if do_resume:
                return True, "pdf ok"
            return False, "answers timed out"

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "applications" / "acme-swe").mkdir(parents=True)
        with patch.object(daily_run, "ROOT", root), patch.object(
            daily_run, "_tailor_phase", side_effect=fake_phase
        ):
            ok, detail = daily_run.tailor_with_cursor(
                "acme-swe",
                {"company_name": "Acme", "title": "SWE Intern", "url": "https://ex"},
                timeout=1,
                do_resume=True,
                do_answers=True,
            )
        self.assertTrue(ok, detail)
        self.assertIn("answers failed", detail)

    def test_cover_only_runs_one_phase(self) -> None:
        from unittest.mock import patch

        import daily_run

        calls: list[tuple[bool, bool, bool]] = []

        def fake_phase(slug, listing, timeout, *, do_resume, do_answers, do_cover=False):
            calls.append((do_resume, do_answers, do_cover))
            return True, "letter ok"

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "applications" / "acme-swe").mkdir(parents=True)
        with patch.object(daily_run, "ROOT", root), patch.object(
            daily_run, "_tailor_phase", side_effect=fake_phase
        ):
            ok, detail = daily_run.tailor_with_cursor(
                "acme-swe",
                {"company_name": "Acme", "title": "SWE Intern", "url": "https://ex"},
                timeout=1,
                do_resume=False,
                do_answers=False,
                do_cover=True,
            )
        self.assertTrue(ok, detail)
        self.assertEqual(calls, [(False, False, True)])
        self.assertIn("letter ok", detail)

    def test_all_three_runs_resume_answers_cover(self) -> None:
        from unittest.mock import patch

        import daily_run

        calls: list[tuple[bool, bool, bool]] = []

        def fake_phase(slug, listing, timeout, *, do_resume, do_answers, do_cover=False):
            calls.append((do_resume, do_answers, do_cover))
            return True, "ok"

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "applications" / "acme-swe").mkdir(parents=True)
        with patch.object(daily_run, "ROOT", root), patch.object(
            daily_run, "_tailor_phase", side_effect=fake_phase
        ):
            ok, detail = daily_run.tailor_with_cursor(
                "acme-swe",
                {"company_name": "Acme", "title": "SWE Intern", "url": "https://ex"},
                timeout=1,
                do_resume=True,
                do_answers=True,
                do_cover=True,
            )
        self.assertTrue(ok, detail)
        self.assertEqual(
            calls,
            [(True, False, False), (False, True, False), (False, False, True)],
        )

    def test_resume_failure_skips_cover(self) -> None:
        from unittest.mock import patch

        import daily_run

        calls: list[tuple[bool, bool, bool]] = []

        def fake_phase(slug, listing, timeout, *, do_resume, do_answers, do_cover=False):
            calls.append((do_resume, do_answers, do_cover))
            if do_resume:
                return False, "no pdf"
            return True, "should not run"

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "applications" / "acme-swe").mkdir(parents=True)
        with patch.object(daily_run, "ROOT", root), patch.object(
            daily_run, "_tailor_phase", side_effect=fake_phase
        ):
            ok, detail = daily_run.tailor_with_cursor(
                "acme-swe",
                {"company_name": "Acme", "title": "SWE Intern", "url": "https://ex"},
                timeout=1,
                do_resume=True,
                do_answers=False,
                do_cover=True,
            )
        self.assertFalse(ok, detail)
        self.assertEqual(calls, [(True, False, False)])


class AnswersPromptForbidsVisibleBrowser(unittest.TestCase):
    def test_no_handoff_or_manual_browse(self) -> None:
        import daily_run

        self.assertIn("Never open a visible browser", daily_run.ANSWERS_NO_VISIBLE_BROWSER)
        self.assertIn("$B connect", daily_run.ANSWERS_NO_VISIBLE_BROWSER)
        self.assertIn("$B handoff", daily_run.ANSWERS_NO_VISIBLE_BROWSER)
        source = Path(daily_run.__file__).read_text(encoding="utf-8")
        self.assertNotIn("If you browse by hand", source)
        self.assertNotIn("CAPTCHA: $B handoff", source)
        self.assertIn("leave showmolbio off", source)
        self.assertIn("Do not run latexmk -C", source)
        self.assertIn("First_Last_resume.pdf", source)
        self.assertIn("cover_letter.md", source)


class SubmitPdfPrompt(unittest.TestCase):
    def test_resume_task_uses_first_last_resume(self) -> None:
        import daily_run
        from check_resume import submit_pdf_name

        text = daily_run._resume_task("applications/acme-swe", fix_hint="")
        self.assertIn(submit_pdf_name(), text)
        self.assertIn("cp resume.pdf", text)
        self.assertIn("Do not leave the submit PDF named resume.pdf", text)


class CoverLetterPrompt(unittest.TestCase):
    def test_cover_phase_writes_cover_letter_md(self) -> None:
        from unittest.mock import patch

        import daily_run

        captured: list[str] = []
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        folder = root / "applications" / "acme-swe"
        folder.mkdir(parents=True)
        (folder / "job.md").write_text("# Acme — SWE Intern\n", encoding="utf-8")

        def fake_run(cmd, timeout, cwd, env, slug=None):
            captured.append(cmd[-1])
            (folder / daily_run.COVER_LETTER_NAME).write_text(
                "Dear Team,\n\n" + ("word " * 50) + "\n\nAlex Rivera\n",
                encoding="utf-8",
            )
            return 0, "ok", False

        with patch.object(daily_run, "ROOT", root), patch.object(
            daily_run, "cursor_agent_argv", return_value=["agent"]
        ), patch.object(daily_run, "run_agent_cmd", side_effect=fake_run):
            ok, detail = daily_run._tailor_phase(
                "acme-swe",
                {"company_name": "Acme", "title": "SWE Intern", "url": "https://ex"},
                1,
                do_resume=False,
                do_answers=False,
                do_cover=True,
            )
        self.assertTrue(ok, detail)
        prompt = captured[0]
        self.assertIn("cover_letter.md", prompt)
        self.assertIn("writing.md", prompt)
        self.assertIn("Voice and stories", prompt)
        self.assertIn("220-380", prompt)
        self.assertIn("cause and effect", prompt)
        self.assertIn("not novel-like", prompt)
        self.assertNotIn("harvest_apply_form.py", prompt)
        self.assertIn("Do not edit", prompt)
        self.assertNotIn("latexmk -pdf", prompt)


class NeedsResume(unittest.TestCase):
    def setUp(self) -> None:
        from unittest.mock import patch

        import daily_run

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "applications").mkdir()
        p = patch.object(daily_run, "ROOT", self.root)
        p.start()
        self.addCleanup(p.stop)

    def test_unseen_needs_resume(self) -> None:
        import daily_run

        self.assertTrue(daily_run._needs_resume(None))

    def test_tailored_without_pdf_retries(self) -> None:
        import daily_run

        slug = "acme-swe"
        (self.root / "applications" / slug).mkdir()
        rec = {"status": "tailored", "slug": slug}
        self.assertTrue(daily_run._needs_resume(rec))
        (self.root / "applications" / slug / "resume.pdf").write_bytes(pdf_bytes(1))
        self.assertFalse(daily_run._needs_resume(rec))

    def test_tailored_two_page_pdf_retries(self) -> None:
        import daily_run

        slug = "acme-swe"
        (self.root / "applications" / slug).mkdir()
        (self.root / "applications" / slug / "resume.pdf").write_bytes(pdf_bytes(2))
        rec = {"status": "tailored", "slug": slug}
        self.assertTrue(daily_run._needs_resume(rec))

    def test_skipped_duplicate_without_pdf_retries(self) -> None:
        import daily_run

        slug = "acme-swe"
        (self.root / "applications" / slug).mkdir()
        rec = {"status": "skipped_duplicate", "slug": slug}
        self.assertTrue(daily_run._needs_resume(rec))

    def test_skipped_fit_does_not_retry(self) -> None:
        import daily_run

        self.assertFalse(daily_run._needs_resume({"status": "skipped_fit", "slug": "x"}))

    def test_skipped_overflow_retries(self) -> None:
        import daily_run

        self.assertTrue(daily_run._needs_resume({"status": "skipped_overflow"}))

    def test_one_page_heading_fail_retries(self) -> None:
        import daily_run

        slug = "acme-swe"
        folder = self.root / "applications" / slug
        folder.mkdir()
        (folder / "resume.pdf").write_bytes(pdf_bytes(1))
        folder.joinpath("resume.tex").write_text(
            r"""
\resumeProjectHeading
    {\textbf{Pananosis Laboratories} $|$ \emph{Python, EC2, Batch Computing, Protein Language Models (ESM, ProtTrans), extra filler words}}{Dec. 2022 -- Present}
""",
            encoding="utf-8",
        )
        rec = {"status": "tailored", "slug": slug}
        self.assertTrue(daily_run._needs_resume(rec))

    def test_chrome_job_md_retries_even_with_one_page_pdf(self) -> None:
        import daily_run

        slug = "acme-swe"
        folder = self.root / "applications" / slug
        folder.mkdir()
        (folder / "resume.pdf").write_bytes(pdf_bytes(1))
        (folder / "job.md").write_text(
            "# Co — Role\n\n## Job description\n\n"
            "Skip to main content\nDeutsch English language picker\n"
            "Privacy Hub Terms of Service Your Privacy Choices\n",
            encoding="utf-8",
        )
        rec = {"status": "tailored", "slug": slug}
        self.assertTrue(daily_run._needs_resume(rec))

    def test_listing_from_folder_reads_job_md(self) -> None:
        import daily_run

        slug = "acme-swe"
        folder = self.root / "applications" / slug
        folder.mkdir()
        (folder / "job.md").write_text(
            "# Acme — SWE Intern\n\n- Source: https://example.com/jobs/1\n"
            "- Listing id: abc-123\n- Location: NYC\n- Category: Software\n",
            encoding="utf-8",
        )
        listing = daily_run.listing_from_folder(slug)
        self.assertEqual(listing["company_name"], "Acme")
        self.assertEqual(listing["title"], "SWE Intern")
        self.assertEqual(listing["url"], "https://example.com/jobs/1")
        self.assertEqual(listing["id"], "abc-123")


class PageOverflowRetry(unittest.TestCase):
    def setUp(self) -> None:
        from unittest.mock import patch

        import daily_run

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        folder = self.root / "applications" / "acme-swe"
        folder.mkdir(parents=True)
        (self.root / "master").mkdir()
        (self.root / "master" / "resume.tex").write_text("% master\n", encoding="utf-8")
        self.folder = folder
        self.listing = {
            "company_name": "Acme",
            "title": "SWE Intern",
            "url": "https://ex",
        }
        p_root = patch.object(daily_run, "ROOT", self.root)
        p_root.start()
        self.addCleanup(p_root.stop)
        p_retries = patch.object(daily_run, "page_retries", return_value=2)
        p_retries.start()
        self.addCleanup(p_retries.stop)
        p_log = patch.object(daily_run, "log")
        p_log.start()
        self.addCleanup(p_log.stop)

    def _run(self, fake_run, fake_check):
        from unittest.mock import patch

        import daily_run

        with patch.object(
            daily_run, "cursor_agent_argv", return_value=["agent"]
        ), patch.object(daily_run, "run_agent_cmd", side_effect=fake_run), patch.object(
            daily_run, "format_check_resume", side_effect=fake_check
        ):
            return daily_run._tailor_phase(
                "acme-swe",
                self.listing,
                1,
                do_resume=True,
                do_answers=False,
                do_cover=False,
            )

    def test_retries_then_accepts_one_page(self) -> None:
        prompts: list[str] = []
        checks = [
            (False, "FAIL\n- PDF is 2 pages; must be exactly 1"),
            (True, "OK"),
        ]

        def fake_run(cmd, timeout, cwd, env, slug=None):
            prompts.append(cmd[-1])
            (self.folder / "resume.pdf").write_bytes(pdf_bytes(2 if len(prompts) == 1 else 1))
            return 0, "ok", False

        def fake_check(slug):
            return checks.pop(0)

        ok, detail = self._run(fake_run, fake_check)
        self.assertTrue(ok, detail)
        self.assertEqual(len(prompts), 2)
        self.assertIn("already reset", prompts[0])
        self.assertIn("HARD FAIL", prompts[1])
        self.assertIn("PDF is 2 pages", prompts[1])
        self.assertIn("Do not copy master/resume.tex again", prompts[1])
        self.assertIn("Python will reject any PDF", prompts[0])

    def test_gives_up_after_page_retries(self) -> None:
        prompts: list[str] = []
        fail = (False, "FAIL\n- PDF is 2 pages; must be exactly 1")

        def fake_run(cmd, timeout, cwd, env, slug=None):
            prompts.append(cmd[-1])
            (self.folder / "resume.pdf").write_bytes(pdf_bytes(2))
            return 0, "ok", False

        def fake_check(slug):
            return fail

        ok, detail = self._run(fake_run, fake_check)
        self.assertFalse(ok, detail)
        self.assertIn("PDF is 2 pages", detail)
        self.assertEqual(len(prompts), 3)

    def test_heading_fail_retries(self) -> None:
        prompts: list[str] = []
        checks = [
            (False, "FAIL\n- project heading 120 chars (budget 88); date will collide"),
            (True, "OK"),
        ]

        def fake_run(cmd, timeout, cwd, env, slug=None):
            prompts.append(cmd[-1])
            (self.folder / "resume.pdf").write_bytes(pdf_bytes(1))
            return 0, "ok", False

        def fake_check(slug):
            return checks.pop(0)

        ok, detail = self._run(fake_run, fake_check)
        self.assertTrue(ok, detail)
        self.assertEqual(len(prompts), 2)
        self.assertIn("HARD FAIL", prompts[1])
        self.assertIn("heading", prompts[1])

    def test_dns_error_retries_then_succeeds(self) -> None:
        prompts: list[str] = []

        def fake_run(cmd, timeout, cwd, env, slug=None):
            prompts.append(cmd[-1])
            if len(prompts) == 1:
                return 1, "Error: [unavailable] getaddrinfo ENOTFOUND api2.cursor.sh", False
            (self.folder / "resume.pdf").write_bytes(pdf_bytes(1))
            return 0, "ok", False

        def fake_check(slug):
            return True, "OK"

        ok, detail = self._run(fake_run, fake_check)
        self.assertTrue(ok, detail)
        self.assertEqual(len(prompts), 2)

    def test_timeout_without_pdf_retries(self) -> None:
        prompts: list[str] = []

        def fake_run(cmd, timeout, cwd, env, slug=None):
            prompts.append(cmd[-1])
            if len(prompts) == 1:
                return None, "", True
            (self.folder / "resume.pdf").write_bytes(pdf_bytes(1))
            return 0, "ok", False

        def fake_check(slug):
            return True, "OK"

        ok, detail = self._run(fake_run, fake_check)
        self.assertTrue(ok, detail)
        self.assertEqual(len(prompts), 2)

    def test_is_page_overflow_parser(self) -> None:
        import daily_run

        self.assertTrue(daily_run.is_page_overflow("FAIL\n- PDF is 2 pages; must be exactly 1"))
        self.assertFalse(daily_run.is_page_overflow("OK"))
        self.assertFalse(daily_run.is_page_overflow("PDF is 1 pages; must be exactly 1"))
        self.assertFalse(daily_run.is_page_overflow("project heading 99 chars"))
        self.assertTrue(
            daily_run.is_transient_agent_error(
                "Error: [unavailable] getaddrinfo ENOTFOUND api2.cursor.sh"
            )
        )
        self.assertTrue(daily_run.is_transient_agent_error("Connection lost, reconnecting"))
        self.assertTrue(daily_run.is_transient_agent_error("cursor agent timed out after 600s"))
        self.assertFalse(daily_run.is_transient_agent_error("not logged in"))


if __name__ == "__main__":
    unittest.main()
