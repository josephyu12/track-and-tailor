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

        def fake_phase(slug, listing, timeout, *, do_resume, do_answers):
            calls.append((do_resume, do_answers))
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
        self.assertEqual(calls, [(True, False), (False, True)])
        self.assertEqual(started, [True])
        self.assertIn("ok", detail)

    def test_resume_failure_skips_answers(self) -> None:
        from unittest.mock import patch

        import daily_run

        calls: list[tuple[bool, bool]] = []

        def fake_phase(slug, listing, timeout, *, do_resume, do_answers):
            calls.append((do_resume, do_answers))
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
        self.assertEqual(calls, [(True, False)])
        self.assertIn("timed out", detail)

    def test_resume_ok_is_success_even_if_answers_fail(self) -> None:
        from unittest.mock import patch

        import daily_run

        def fake_phase(slug, listing, timeout, *, do_resume, do_answers):
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
        (self.root / "applications" / slug / "resume.pdf").write_bytes(b"%PDF")
        self.assertFalse(daily_run._needs_resume(rec))

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


if __name__ == "__main__":
    unittest.main()
