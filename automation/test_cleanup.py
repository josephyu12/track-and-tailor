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
        self.assertTrue(folder.is_dir())
        self.assertEqual(stats["stubs"], 0)

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
