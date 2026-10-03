#!/usr/bin/env python3
"""Tailor-status file must not lose updates when many custom jobs run at once."""

from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dashboard  # noqa: E402
from test_check_resume import pdf_bytes  # noqa: E402


class StatusConcurrency(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.state = root / "state"
        self.apps = root / "apps"
        self.state.mkdir()
        self.apps.mkdir()
        self.status_path = self.state / "tailor_status.json"
        for p in (
            patch.object(dashboard, "STATE", self.state),
            patch.object(dashboard, "TAILOR_STATUS", self.status_path),
            patch.object(dashboard, "APPS", self.apps),
        ):
            p.start()
            self.addCleanup(p.stop)

    def test_concurrent_done_writes_keep_every_slug(self) -> None:
        n = 24

        def worker(i: int) -> None:
            slug = f"job-{i}"
            dashboard._set_status(slug, "running", "resume+answers")
            dashboard._set_status(slug, "done", "ok")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        data = dashboard._status()
        self.assertEqual(len(data), n)
        for i in range(n):
            rec = data.get(f"job-{i}") or {}
            self.assertEqual(rec.get("state"), "done", msg=f"job-{i} {rec}")

    def test_running_with_newer_pdf_becomes_done(self) -> None:
        slug = "acme-swe"
        folder = self.apps / slug
        folder.mkdir()
        dashboard._set_status(slug, "running", "resume")
        time.sleep(0.05)
        (folder / "resume.pdf").write_bytes(pdf_bytes(1))
        rec = dashboard._status()[slug]
        self.assertEqual(rec["state"], "done")

    def test_running_with_two_page_pdf_stays_running(self) -> None:
        slug = "acme-swe"
        folder = self.apps / slug
        folder.mkdir()
        dashboard._set_status(slug, "running", "resume")
        time.sleep(0.05)
        (folder / "resume.pdf").write_bytes(pdf_bytes(2))
        rec = dashboard._status()[slug]
        self.assertEqual(rec["state"], "running")

    def test_running_both_with_only_pdf_stays_running(self) -> None:
        slug = "acme-swe"
        folder = self.apps / slug
        folder.mkdir()
        dashboard._set_status(slug, "running", "resume+answers")
        time.sleep(0.05)
        (folder / "resume.pdf").write_bytes(b"%PDF")
        rec = dashboard._status()[slug]
        self.assertEqual(rec["state"], "running")

    def test_running_cover_with_newer_letter_becomes_done(self) -> None:
        slug = "acme-swe"
        folder = self.apps / slug
        folder.mkdir()
        dashboard._set_status(slug, "running", "cover")
        with dashboard._STATUS_LOCK:
            data = dashboard._load_status_unlocked()
            data[slug]["at"] = (datetime.now() - timedelta(seconds=5)).isoformat(
                timespec="seconds"
            )
            dashboard._write_status_unlocked(data)
        (folder / "cover_letter.md").write_text(
            "Dear Team,\n\n" + ("word " * 40), encoding="utf-8"
        )
        rec = dashboard._status()[slug]
        self.assertEqual(rec["state"], "done")

    def test_running_resume_and_cover_with_only_pdf_stays_running(self) -> None:
        slug = "acme-swe"
        folder = self.apps / slug
        folder.mkdir()
        dashboard._set_status(slug, "running", "resume+cover")
        time.sleep(0.05)
        (folder / "resume.pdf").write_bytes(b"%PDF")
        rec = dashboard._status()[slug]
        self.assertEqual(rec["state"], "running")

    def test_queued_survives_stale_timer(self) -> None:
        with patch.object(
            dashboard, "_cfg", return_value={"agent_timeout_s": 1, "page_retries": 0}
        ):
            dashboard._set_status("x", "queued", "resume+answers")
            with dashboard._STATUS_LOCK:
                data = dashboard._load_status_unlocked()
                data["x"]["at"] = (datetime.now() - timedelta(seconds=200)).isoformat(
                    timespec="seconds"
                )
                dashboard._write_status_unlocked(data)
            rec = dashboard._status()["x"]
        self.assertEqual(rec["state"], "queued")

    def test_fresh_running_without_pdf_stays_running(self) -> None:
        dashboard._set_status("x", "running", "resume+answers")
        rec = dashboard._status()["x"]
        self.assertEqual(rec["state"], "running")

    def test_stale_running_without_artifacts_errors(self) -> None:
        with patch.object(
            dashboard, "_cfg", return_value={"agent_timeout_s": 1, "page_retries": 0}
        ):
            dashboard._set_status("x", "running", "resume+answers")
            with dashboard._STATUS_LOCK:
                data = dashboard._load_status_unlocked()
                data["x"]["at"] = (datetime.now() - timedelta(seconds=200)).isoformat(
                    timespec="seconds"
                )
                dashboard._write_status_unlocked(data)
            rec = dashboard._status()["x"]
        self.assertEqual(rec["state"], "error")

    def test_dead_pid_without_pdf_errors(self) -> None:
        dashboard._set_status("x", "running", "resume+answers")
        with dashboard._STATUS_LOCK:
            data = dashboard._load_status_unlocked()
            data["x"]["pid"] = 1
            dashboard._write_status_unlocked(data)
        rec = dashboard._status()["x"]
        self.assertEqual(rec["state"], "error")
        self.assertIn("restarted", rec.get("detail") or "")


def _write_job(
    apps: Path, slug: str, company: str, title: str, url: str, *, pdf: bool = False
) -> None:
    folder = apps / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "job.md").write_text(
        f"# {company} — {title}\n\n- Date: 2026-08-21\n- Source: {url}\n- Slug: {slug}\n",
        encoding="utf-8",
    )
    if pdf:
        (folder / "resume.pdf").write_bytes(b"%PDF")


class AppliedPersist(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.state = root / "state"
        self.apps = root / "apps"
        self.state.mkdir()
        self.apps.mkdir()
        self.applied_path = self.state / "applied.json"
        for p in (
            patch.object(dashboard, "STATE", self.state),
            patch.object(dashboard, "APPLIED_PATH", self.applied_path),
            patch.object(dashboard, "APPS", self.apps),
        ):
            p.start()
            self.addCleanup(p.stop)

    def test_check_survives_reload(self) -> None:
        _write_job(self.apps, "acme-swe", "Acme", "Software Engineer Intern", "https://example.com/1")
        dashboard.set_applied("acme-swe", True, via="toggle")
        self.assertTrue(self.applied_path.is_file())
        data = dashboard._applied()
        self.assertTrue(data["acme-swe"]["applied"])
        self.assertTrue(dashboard.is_applied("acme-swe"))

    def test_uncheck_removes(self) -> None:
        _write_job(self.apps, "acme-swe", "Acme", "Software Engineer Intern", "https://example.com/1")
        dashboard.set_applied("acme-swe", True, via="toggle")
        dashboard.set_applied("acme-swe", False, via="toggle")
        self.assertFalse(dashboard.is_applied("acme-swe"))
        self.assertNotIn("acme-swe", dashboard._applied())

    def test_duplicate_listings_share_applied(self) -> None:
        _write_job(
            self.apps,
            "amd-swe-ca",
            "AMD",
            "Software Engineer Intern/Co-op",
            "https://careers.amd.com/jobs/90891",
        )
        _write_job(
            self.apps,
            "amd-swe-tx",
            "AMD",
            "Software Engineer Intern/Co-op",
            "https://careers.amd.com/jobs/90947",
        )
        dashboard.set_applied("amd-swe-ca", True, via="toggle")
        self.assertTrue(dashboard.is_applied("amd-swe-ca"))
        self.assertTrue(dashboard.is_applied("amd-swe-tx"))

    def test_concurrent_checks_all_persist(self) -> None:
        n = 16
        for i in range(n):
            _write_job(
                self.apps,
                f"job-{i}",
                f"Co{i}",
                "Software Engineer Intern",
                f"https://example.com/{i}",
            )

        def worker(i: int) -> None:
            dashboard.set_applied(f"job-{i}", True, via="toggle")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        for i in range(n):
            self.assertTrue(dashboard.is_applied(f"job-{i}"), msg=f"job-{i}")


class AnalyzeGates(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.apps = root / "apps"
        self.apps.mkdir()
        p = patch.object(dashboard, "APPS", self.apps)
        p.start()
        self.addCleanup(p.stop)

    def test_fall_only_alerts_and_does_not_continue(self) -> None:
        with patch.object(dashboard, "start_tailor") as tailor:
            slug, err = dashboard.analyze(
                {
                    "company": "Acme",
                    "role": "Software Engineer Intern",
                    "jd": "Fall 2026 internship. Python backend. 12 weeks starting September 2026.",
                    "mode": "run",
                    "do_resume": "1",
                    "do_answers": "1",
                }
            )
        self.assertEqual(slug, "")
        self.assertIn("Summer 2027", err)
        self.assertIn("Not continuing", err)
        tailor.assert_not_called()
        self.assertFalse(any(self.apps.iterdir()))

    def test_exact_url_duplicate_alerts_and_does_not_scrape(self) -> None:
        url = "https://boards.greenhouse.io/acme/jobs/123"
        _write_job(self.apps, "acme-swe", "Acme", "SWE Intern", url, pdf=True)
        with patch.object(dashboard, "scrape_one", side_effect=AssertionError("should not scrape")):
            with patch.object(dashboard, "start_tailor") as tailor:
                slug, err = dashboard.analyze(
                    {
                        "url": url,
                        "company": "Other",
                        "role": "Other Intern",
                        "mode": "run",
                        "do_resume": "1",
                    }
                )
        self.assertEqual(slug, "")
        self.assertIn("already saved as acme-swe", err)
        self.assertIn("Not continuing", err)
        tailor.assert_not_called()

    def test_tracking_query_is_treated_as_same_url(self) -> None:
        _write_job(
            self.apps,
            "acme-swe",
            "Acme",
            "SWE Intern",
            "https://boards.greenhouse.io/acme/jobs/123",
            pdf=True,
        )
        with patch.object(dashboard, "scrape_one", side_effect=AssertionError("should not scrape")):
            with patch.object(dashboard, "start_tailor") as tailor:
                slug, err = dashboard.analyze(
                    {
                        "url": "https://boards.greenhouse.io/acme/jobs/123?utm_source=Simplify",
                        "mode": "run",
                        "do_resume": "1",
                    }
                )
        self.assertEqual(slug, "")
        self.assertIn("already saved as acme-swe", err)
        tailor.assert_not_called()

    def test_same_company_title_does_not_rerun_tailor(self) -> None:
        _write_job(
            self.apps,
            "anduril-industries-research-scientist",
            "Anduril Industries",
            "Research Scientist",
            "https://job-boards.greenhouse.io/andurilindustries/jobs/5203023007",
            pdf=True,
        )
        scraped = {
            "ok": True,
            "company": "Anduril Industries",
            "role": "Research Scientist",
            "location": "Huntsville, AL",
            "jd_text": "Summer 2027 research scientist intern. Python.",
            "questions": [],
            "error": None,
        }
        with patch.object(dashboard, "scrape_one", return_value=scraped):
            with patch.object(dashboard, "start_tailor") as tailor:
                slug, err = dashboard.analyze(
                    {
                        "url": "https://www.anduril.com/careers/research-scientist",
                        "mode": "run",
                        "do_resume": "1",
                        "do_answers": "1",
                    }
                )
        self.assertEqual(slug, "")
        self.assertIn("anduril-industries-research-scientist", err)
        self.assertIn("Not continuing", err)
        tailor.assert_not_called()

    def test_missing_pdf_reuses_slug_and_tailors(self) -> None:
        url = "https://boards.greenhouse.io/acme/jobs/123"
        _write_job(self.apps, "acme-swe", "Acme", "SWE Intern", url)
        scraped = {
            "ok": True,
            "company": "Acme",
            "role": "SWE Intern",
            "location": "",
            "jd_text": "Summer 2027 software engineer intern. Python backend.",
            "questions": [],
            "error": None,
        }
        with patch.object(dashboard, "scrape_one", return_value=scraped):
            with patch.object(dashboard, "write_job_md"):
                with patch.object(dashboard, "start_tailor") as tailor:
                    with patch.object(dashboard, "_cfg", return_value={"fit_min_score": 0.4}):
                        slug, err = dashboard.analyze(
                            {
                                "url": url,
                                "mode": "run",
                                "do_resume": "1",
                                "do_answers": "1",
                            }
                        )
        self.assertEqual(err, "")
        self.assertEqual(slug, "acme-swe")
        tailor.assert_called_once()

    def test_in_flight_url_does_not_start_a_second_scrape(self) -> None:
        url = "https://job-boards.greenhouse.io/andurilindustries/jobs/5203023007"
        dashboard._IN_FLIGHT_URLS.add(dashboard.canonical_url(url))
        try:
            with patch.object(dashboard, "scrape_one", side_effect=AssertionError("should not scrape")):
                with patch.object(dashboard, "start_tailor") as tailor:
                    slug, err = dashboard.analyze({"url": url, "mode": "run", "do_resume": "1"})
            self.assertEqual(slug, "")
            self.assertIn("already being analyzed", err)
            tailor.assert_not_called()
        finally:
            dashboard._IN_FLIGHT_URLS.clear()


class DeleteKillsTailor(unittest.TestCase):
    def setUp(self) -> None:
        import dedupe

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.state = root / "state"
        self.apps = root / "apps"
        self.state.mkdir()
        self.apps.mkdir()
        self.seen = self.state / "seen.json"
        self.seen.write_text("{}\n", encoding="utf-8")
        for p in (
            patch.object(dashboard, "STATE", self.state),
            patch.object(dashboard, "TAILOR_STATUS", self.state / "tailor_status.json"),
            patch.object(dashboard, "APPS", self.apps),
            patch.object(dashboard, "APPLIED_PATH", self.state / "applied.json"),
            patch.object(dashboard, "SEEN_PATH", self.seen),
            patch.object(dedupe, "STATE", self.state),
            patch.object(dedupe, "DELETED_PATH", self.state / "deleted.json"),
        ):
            p.start()
            self.addCleanup(p.stop)

    def test_delete_kills_tailor_process_group(self) -> None:
        import os
        import subprocess

        slug = "acme-swe"
        _write_job(self.apps, slug, "Acme", "SWE Intern", "https://example.com/jobs/1")
        script = (
            "import os, time\n"
            "if os.fork() == 0:\n"
            "    while True:\n"
            "        time.sleep(1)\n"
            "while True:\n"
            "    time.sleep(1)\n"
        )
        proc = subprocess.Popen(
            [sys.executable, "-c", script],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.addCleanup(lambda: proc.poll() is not None or proc.kill())
        (self.apps / slug / ".tailor.pid").write_text(str(proc.pid), encoding="utf-8")
        err = dashboard.delete_application(slug)
        self.assertIsNone(err)
        deadline = time.time() + 3
        while proc.poll() is None and time.time() < deadline:
            time.sleep(0.05)
        self.assertIsNotNone(proc.poll(), "tailor process group was still alive after delete")
        self.assertFalse((self.apps / slug).exists())
        try:
            os.killpg(proc.pid, 0)
            alive = True
        except (ProcessLookupError, PermissionError, OSError):
            alive = False
        self.assertFalse(alive)


class CoverLetterUi(unittest.TestCase):
    def test_add_form_has_unchecked_cover_checkbox(self) -> None:
        html = dashboard.add_form()
        self.assertIn('name="do_cover"', html)
        self.assertIn("Draft cover letter", html)
        self.assertNotIn('name="do_cover" value="1" checked', html)

    def test_job_page_has_make_cover_letter(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        apps = Path(self.tmp.name) / "apps"
        apps.mkdir()
        _write_job(apps, "acme-swe", "Acme", "SWE Intern", "https://example.com/j")
        with patch.object(dashboard, "APPS", apps):
            body = dashboard.app_body("acme-swe")
        self.assertIn("Make cover letter", body)
        self.assertIn('name="do_cover"', body)
        self.assertIn("None yet", body)

    def test_job_page_shows_existing_letter(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        apps = Path(self.tmp.name) / "apps"
        apps.mkdir()
        _write_job(apps, "acme-swe", "Acme", "SWE Intern", "https://example.com/j")
        (apps / "acme-swe" / "cover_letter.md").write_text(
            "Dear Team,\n\nI noticed how Acme ships the compiler in pieces.\n",
            encoding="utf-8",
        )
        with patch.object(dashboard, "APPS", apps):
            body = dashboard.app_body("acme-swe")
        self.assertIn("Rerun cover letter", body)
        self.assertIn("I noticed how Acme ships the compiler in pieces.", body)


class CatalogPdfCheck(unittest.TestCase):
    def test_list_uses_page_count_not_full_checker(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        apps = Path(tmp.name) / "apps"
        folder = apps / "acme-swe"
        _write_job(apps, "acme-swe", "Acme", "SWE Intern", "https://example.com/j")
        (folder / "resume.pdf").write_bytes(pdf_bytes(1))
        with patch.object(dashboard, "APPS", apps):
            with patch.object(dashboard, "resume_ready", side_effect=AssertionError("full")):
                rec = dashboard.parse_job_folder(folder)
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertTrue(rec["pdf_ok"])

    def test_job_page_still_runs_full_checker(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        apps = Path(tmp.name) / "apps"
        folder = apps / "acme-swe"
        _write_job(apps, "acme-swe", "Acme", "SWE Intern", "https://example.com/j")
        (folder / "resume.pdf").write_bytes(pdf_bytes(1))
        with patch.object(dashboard, "APPS", apps):
            with patch.object(dashboard, "resume_ready", return_value=(False, ["two pages"])):
                rec = dashboard.parse_job_folder(folder, full_pdf=True)
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertFalse(rec["pdf_ok"])


class JobsTablePdf(unittest.TestCase):
    def test_jobs_table_warns_when_pdf_not_ok(self) -> None:
        html = dashboard.jobs_table(
            [
                {
                    "slug": "acme-swe",
                    "company": "Acme",
                    "title": "SWE Intern",
                    "date": "2026-09-02",
                    "url": "https://example.com/j",
                    "pdf": True,
                    "pdf_ok": False,
                    "pdf_name": "Joseph_Yu_resume.pdf",
                    "keep": False,
                    "applied": False,
                    "fit": {},
                    "needs": 0,
                }
            ]
        )
        self.assertIn("needs tailor", html)
        self.assertIn("btn-warn", html)

    def test_jobs_table_ok_pdf_is_green(self) -> None:
        html = dashboard.jobs_table(
            [
                {
                    "slug": "acme-swe",
                    "company": "Acme",
                    "title": "SWE Intern",
                    "date": "2026-09-02",
                    "url": "https://example.com/j",
                    "pdf": True,
                    "pdf_ok": True,
                    "pdf_name": "Joseph_Yu_resume.pdf",
                    "keep": False,
                    "applied": False,
                    "fit": {},
                    "needs": 0,
                }
            ]
        )
        self.assertNotIn("needs tailor", html)
        self.assertIn("btn-pdf", html)
        self.assertIn("Favorite", html)


class Favorite(unittest.TestCase):
    def test_row_shows_favorite_checkbox(self) -> None:
        html = dashboard.jobs_table(
            [
                {
                    "slug": "acme-swe",
                    "company": "Acme",
                    "title": "SWE Intern",
                    "date": "2026-10-02",
                    "url": "https://example.com/j",
                    "pdf": False,
                    "pdf_ok": False,
                    "pdf_name": "Alex_Rivera_resume.pdf",
                    "keep": True,
                    "applied": False,
                    "fit": {},
                    "needs": 0,
                }
            ]
        )
        self.assertIn("Favorite", html)
        self.assertIn("checked", html)
        self.assertIn('class="favorite"', html)

    def test_favorites_view_hides_the_rest(self) -> None:
        rows = [
            {
                "slug": "kept-role",
                "company": "Acme",
                "title": "SWE Intern",
                "date": "2026-10-02",
                "url": "https://example.com/a",
                "pdf": True,
                "pdf_ok": True,
                "keep": True,
                "applied": False,
                "fit": {},
                "needs": 0,
            },
            {
                "slug": "other-role",
                "company": "Other",
                "title": "SWE Intern",
                "date": "2026-10-02",
                "url": "https://example.com/b",
                "pdf": True,
                "pdf_ok": True,
                "keep": False,
                "applied": False,
                "fit": {},
                "needs": 0,
            },
        ]
        body = dashboard.overview_body(rows=rows, favorites_only=True)
        self.assertIn("kept-role", body)
        self.assertNotIn("other-role", body)
        self.assertNotIn("Places", body)

    def test_favorite_toggles_keep_file(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        apps = Path(tmp.name) / "apps"
        folder = apps / "acme-swe"
        folder.mkdir(parents=True)
        (folder / "job.md").write_text("# Acme — SWE Intern\n", encoding="utf-8")
        with patch.object(dashboard, "APPS", apps):
            self.assertIsNone(dashboard.set_favorite("acme-swe", True))
            self.assertTrue((folder / ".keep").is_file())
            self.assertIsNone(dashboard.set_favorite("acme-swe", False))
            self.assertFalse((folder / ".keep").exists())


if __name__ == "__main__":
    unittest.main()
