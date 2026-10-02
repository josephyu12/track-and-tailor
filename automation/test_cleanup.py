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
from test_check_resume import pdf_bytes  # noqa: E402


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

    def test_tidy_promotes_named_resume_and_drops_extra_pdf(self) -> None:
        from check_resume import submit_pdf_name
        from cleanup import tidy_folder

        folder = self._folder("acme-swe")
        named = submit_pdf_name()
        (folder / "resume.pdf").write_bytes(b"%PDF-latexmk")
        (folder / "extra.pdf").write_bytes(b"%PDF")
        (folder / "resume.aux").write_text("aux\n", encoding="utf-8")
        removed = tidy_folder(folder)
        self.assertTrue((folder / named).is_file())
        self.assertEqual((folder / named).read_bytes(), b"%PDF-latexmk")
        self.assertFalse((folder / "resume.pdf").exists())
        self.assertFalse((folder / "extra.pdf").exists())
        self.assertFalse((folder / "resume.aux").exists())
        self.assertIn("resume.pdf", removed)
        self.assertIn("extra.pdf", removed)
        self.assertIn("resume.aux", removed)
        self.assertNotIn(named, removed)

    def test_tidy_keeps_existing_named_pdf(self) -> None:
        from check_resume import submit_pdf_name
        from cleanup import tidy_folder

        folder = self._folder("acme-swe")
        named = submit_pdf_name()
        (folder / "resume.pdf").write_bytes(b"%PDF-latexmk")
        (folder / named).write_bytes(b"%PDF-submit")
        removed = tidy_folder(folder)
        self.assertEqual((folder / named).read_bytes(), b"%PDF-submit")
        self.assertFalse((folder / "resume.pdf").exists())
        self.assertIn("resume.pdf", removed)
        self.assertNotIn(named, removed)

    def test_tidy_keeps_cover_letter_md(self) -> None:
        from cleanup import tidy_folder

        folder = self._folder("acme-swe")
        (folder / "resume.pdf").write_bytes(b"%PDF-submit")
        (folder / "cover_letter.md").write_text("Dear Team,\n", encoding="utf-8")
        (folder / "extra.pdf").write_bytes(b"%PDF")
        removed = tidy_folder(folder)
        self.assertTrue((folder / "cover_letter.md").is_file())
        self.assertFalse((folder / "extra.pdf").exists())
        self.assertNotIn("cover_letter.md", removed)

    def test_prune_does_not_cap_unready_job(self) -> None:
        old = time.time() - 400
        complete = self._folder("has-pdf")
        (complete / "job.md").write_text("# Co — Role\n", encoding="utf-8")
        (complete / "resume.pdf").write_bytes(pdf_bytes(1))
        os.utime(complete, (old, old))
        missing = self._folder("no-pdf")
        (missing / "job.md").write_text("# Co2 — Role\n", encoding="utf-8")
        os.utime(missing, (old + 10, old + 10))
        with patch("cleanup.APPS", self.apps):
            stats = prune_applications(21, 1, now=datetime.now())
        self.assertTrue(complete.is_dir())
        self.assertTrue(missing.is_dir())
        self.assertEqual(stats["capped"], 0)

    def test_prune_cap_drops_oldest_complete_keeps_unready(self) -> None:
        old = time.time() - 400
        older = self._folder("older-job")
        (older / "job.md").write_text("# Old — Role\n", encoding="utf-8")
        (older / "resume.pdf").write_bytes(pdf_bytes(1))
        os.utime(older, (old, old))
        newer = self._folder("newer-job")
        (newer / "job.md").write_text("# New — Role\n", encoding="utf-8")
        (newer / "resume.pdf").write_bytes(pdf_bytes(1))
        os.utime(newer, (old + 10, old + 10))
        missing = self._folder("no-pdf")
        (missing / "job.md").write_text("# Pending — Role\n", encoding="utf-8")
        os.utime(missing, (old + 20, old + 20))
        with patch("cleanup.APPS", self.apps):
            stats = prune_applications(21, 1, now=datetime.now())
        self.assertFalse(older.exists())
        self.assertTrue(newer.is_dir())
        self.assertTrue(missing.is_dir())
        self.assertEqual(stats["capped"], 1)

    def test_prune_cap_ignores_pinned(self) -> None:
        old = time.time() - 400
        pinned = self._folder("pinned-job")
        (pinned / "job.md").write_text("# Pin — Role\n", encoding="utf-8")
        (pinned / "resume.pdf").write_bytes(pdf_bytes(1))
        (pinned / ".keep").write_text("", encoding="utf-8")
        os.utime(pinned, (old, old))
        unpinned = self._folder("fresh-job")
        (unpinned / "job.md").write_text("# Fresh — Role\n", encoding="utf-8")
        (unpinned / "resume.pdf").write_bytes(pdf_bytes(1))
        os.utime(unpinned, (old + 10, old + 10))
        with patch("cleanup.APPS", self.apps):
            stats = prune_applications(21, 1, now=datetime.now())
        self.assertTrue(pinned.is_dir())
        self.assertTrue(unpinned.is_dir())
        self.assertEqual(stats["capped"], 0)

    def test_prune_caps_oldest_complete_when_all_have_pdf(self) -> None:
        old = time.time() - 400
        older = self._folder("older-job")
        (older / "job.md").write_text("# Old — Role\n", encoding="utf-8")
        (older / "resume.pdf").write_bytes(pdf_bytes(1))
        os.utime(older, (old, old))
        newer = self._folder("newer-job")
        (newer / "job.md").write_text("# New — Role\n", encoding="utf-8")
        (newer / "resume.pdf").write_bytes(pdf_bytes(1))
        os.utime(newer, (old + 10, old + 10))
        with patch("cleanup.APPS", self.apps):
            stats = prune_applications(21, 1, now=datetime.now())
        self.assertFalse(older.exists())
        self.assertTrue(newer.is_dir())
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
