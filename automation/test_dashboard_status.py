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
        dashboard._set_status(slug, "running", "resume+answers")
        time.sleep(0.05)
        (folder / "resume.pdf").write_bytes(b"%PDF")
        rec = dashboard._status()[slug]
        self.assertEqual(rec["state"], "done")

    def test_fresh_running_without_pdf_stays_running(self) -> None:
        dashboard._set_status("x", "running", "resume+answers")
        rec = dashboard._status()["x"]
        self.assertEqual(rec["state"], "running")

    def test_stale_running_without_artifacts_errors(self) -> None:
        with patch.object(dashboard, "_cfg", return_value={"agent_timeout_s": 1}):
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


def _write_job(apps: Path, slug: str, company: str, title: str, url: str) -> None:
    folder = apps / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "job.md").write_text(
        f"# {company} — {title}\n\n- Date: 2026-08-21\n- Source: {url}\n- Slug: {slug}\n",
        encoding="utf-8",
    )


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


if __name__ == "__main__":
    unittest.main()
