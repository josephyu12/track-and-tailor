#!/usr/bin/env python3
"""Failed-tailor folders must survive cleanup so retry and the dashboard keep them."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cleanup import is_stub, prune_applications  # noqa: E402


class StubPolicy(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.apps = Path(self.tmp.name)

    def _folder(self, name: str) -> Path:
        folder = self.apps / name
        folder.mkdir()
        return folder

    def test_failed_tailor_with_job_md_is_not_stub(self) -> None:
        folder = self._folder("infinitequant-quant-dev")
        (folder / "job.md").write_text(
            "# InfiniteQuant — Quant Dev\n\n## Job description\n\nBuild HFT systems.\n",
            encoding="utf-8",
        )
        (folder / "resume.tex").write_text("% copy of master\n", encoding="utf-8")
        (folder / "application_questions.md").write_text("# Answers\n", encoding="utf-8")
        self.assertFalse(is_stub(folder))

    def test_tex_only_leftover_is_stub(self) -> None:
        folder = self._folder("aborted-copy")
        (folder / "resume.tex").write_text("% copy of master\n", encoding="utf-8")
        self.assertTrue(is_stub(folder))

    def test_pdf_is_never_stub(self) -> None:
        folder = self._folder("done-job")
        (folder / "resume.pdf").write_bytes(b"%PDF")
        self.assertFalse(is_stub(folder))

    def test_prune_keeps_old_failed_tailor(self) -> None:
        folder = self._folder("hung-agent-job")
        (folder / "job.md").write_text(
            "# Co — Role\n\n- Source: https://example.com/job\n\n## Job description\n\nJD\n",
            encoding="utf-8",
        )
        old = time.time() - 400
        os.utime(folder, (old, old))
        with patch("cleanup.APPS", self.apps):
            stats = prune_applications(21, 30, now=datetime.now())
        self.assertTrue(folder.exists())
        self.assertEqual(stats["stubs"], 0)

    def test_tidy_keeps_resume_pdf_and_drops_extra_pdf(self) -> None:
        from cleanup import tidy_folder

        folder = self._folder("acme-swe")
        (folder / "resume.pdf").write_bytes(b"%PDF-submit")
        (folder / "Joseph_Yu_resume.pdf").write_bytes(b"%PDF-copy")
        (folder / "resume.aux").write_text("aux\n", encoding="utf-8")
        removed = tidy_folder(folder)
        self.assertTrue((folder / "resume.pdf").is_file())
        self.assertEqual((folder / "resume.pdf").read_bytes(), b"%PDF-submit")
        self.assertFalse((folder / "Joseph_Yu_resume.pdf").exists())
        self.assertFalse((folder / "resume.aux").exists())
        self.assertIn("Joseph_Yu_resume.pdf", removed)
        self.assertIn("resume.aux", removed)
        self.assertNotIn("resume.pdf", removed)

    def test_prune_caps_missing_pdf_before_complete(self) -> None:
        old = time.time() - 400
        complete = self._folder("has-pdf")
        (complete / "job.md").write_text("# Co — Role\n", encoding="utf-8")
        (complete / "resume.pdf").write_bytes(b"%PDF")
        os.utime(complete, (old, old))
        missing = self._folder("no-pdf")
        (missing / "job.md").write_text("# Co2 — Role\n", encoding="utf-8")
        os.utime(missing, (old + 10, old + 10))
        with patch("cleanup.APPS", self.apps):
            stats = prune_applications(21, 1, now=datetime.now())
        self.assertTrue(complete.is_dir())
        self.assertFalse(missing.exists())
        self.assertEqual(stats["capped"], 1)

    def test_tidy_does_not_refresh_age_for_expiry(self) -> None:
        folder = self._folder("old-job")
        (folder / "job.md").write_text("# Co — Role\n", encoding="utf-8")
        (folder / "resume.pdf").write_bytes(b"%PDF")
        (folder / "resume.aux").write_text("aux\n", encoding="utf-8")
        old = time.time() - 22 * 86400
        os.utime(folder, (old, old))
        os.utime(folder / "job.md", (old, old))
        os.utime(folder / "resume.pdf", (old, old))
        with patch("cleanup.APPS", self.apps):
            stats = prune_applications(21, 30, now=datetime.now())
        self.assertFalse(folder.exists())
        self.assertEqual(stats["expired"], 1)

    def test_prune_deletes_old_tex_only_stub(self) -> None:
        folder = self._folder("empty-leftover")
        (folder / "resume.tex").write_text("%\n", encoding="utf-8")
        old = time.time() - 400
        os.utime(folder, (old, old))
        with patch("cleanup.APPS", self.apps):
            stats = prune_applications(21, 30, now=datetime.now())
        self.assertFalse(folder.exists())
        self.assertEqual(stats["stubs"], 1)


if __name__ == "__main__":
    unittest.main()
