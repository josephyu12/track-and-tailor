#!/usr/bin/env python3
"""Heading/date format checks for tailored resumes."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / ".cursor" / "skills" / "tailor-resume" / "scripts"
sys.path.insert(0, str(SCRIPTS))
from check_resume import (  # noqa: E402
    check_tex,
    gpu_skus,
    heading_budget,
    is_one_page,
    latex_to_visible,
    pdf_page_count,
    resume_ready,
    submit_pdf_name,
    submit_pdf_path,
)

ROOT = Path(__file__).resolve().parents[1]
MASTER = (ROOT / "master" / "resume.example.tex").read_text(encoding="utf-8")

EXAMPLE = r"""
\resumeProjectHeading
    {\textbf{Example Labs} $|$ \emph{Python, AWS, Batch Computing\iftoggle{showprojectgpu}{, A100, L40S}{}}}{Jan. 2025 -- Present}
    \resumeItemListStart
      \resumeItem{Trained ranking models with CUDA GPU batch on \textbf{A100}/\textbf{L40S}}
    \resumeItemListEnd
"""


def pdf_bytes(pages: int) -> bytes:
    """Minimal PDF whose /Type/Page markers match pdf_page_count."""
    if pages < 1:
        raise ValueError("pages")
    kids = " ".join(f"{i + 3} 0 R" for i in range(pages))
    parts = [
        "%PDF-1.1",
        "1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj",
        f"2 0 obj<</Type/Pages/Kids[{kids}]/Count {pages}>>endobj",
    ]
    for i in range(pages):
        parts.append(
            f"{i + 3} 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj"
        )
    parts += ["trailer<</Root 1 0 R>>", "%%EOF"]
    return ("\n".join(parts) + "\n").encode("ascii")


def tex_with_gpu_toggle(on: bool, body: str = EXAMPLE) -> str:
    state = "true" if on else "false"
    return (
        f"\\newtoggle{{showprojectgpu}}\n"
        f"\\toggle{state}{{showprojectgpu}}\n"
        f"{body}\n"
    )


class CheckResume(unittest.TestCase):
    def test_example_master_passes(self) -> None:
        self.assertEqual(check_tex(MASTER, master_tex=MASTER), [])

    def test_heading_budget_comes_from_master(self) -> None:
        self.assertGreater(heading_budget(MASTER), 20)

    def test_gpu_toggle_plus_bullet_fails_overlap(self) -> None:
        issues = check_tex(tex_with_gpu_toggle(True), master_tex=MASTER)
        blob = " ".join(issues)
        self.assertIn("A100", blob)
        self.assertIn("L40S", blob)
        self.assertTrue(any("heading and bullets" in x or "italic heading and bullets" in x for x in issues), issues)

    def test_gpus_only_in_bullets_pass(self) -> None:
        self.assertEqual(check_tex(tex_with_gpu_toggle(False), master_tex=MASTER), [])

    def test_long_heading_without_gpus_still_fails(self) -> None:
        body = r"""
\resumeProjectHeading
    {\textbf{Example Labs} $|$ \emph{Python, AWS, Batch Computing, Hugging Face, CUDA, Kubernetes, Terraform, Observability}}{Jan. 2025 -- Present}
    \resumeItemListStart
      \resumeItem{Shipped an internal reporting API}
    \resumeItemListEnd
"""
        issues = check_tex(tex_with_gpu_toggle(False, body), master_tex=MASTER)
        self.assertTrue(
            any("collide" in x or "chars" in x or "budget" in x for x in issues),
            issues,
        )
        self.assertFalse(any("heading and bullets" in x for x in issues), issues)

    def test_a10_is_not_a_prefix_of_a100(self) -> None:
        self.assertEqual(gpu_skus("trained on A100 GPUs"), {"A100"})
        self.assertEqual(gpu_skus("A10 and A100 and L40S"), {"A10", "A100", "L40S"})

    def test_visible_heading_strips_latex(self) -> None:
        visible = latex_to_visible(
            r"\textbf{Example Labs} $|$ \emph{Python, AWS, Batch Computing}"
        )
        self.assertEqual(
            visible,
            "Example Labs | Python, AWS, Batch Computing",
        )


class PdfPageCount(unittest.TestCase):
    def test_one_and_two_page_fixtures(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        one = Path(tmp.name) / "one.pdf"
        two = Path(tmp.name) / "two.pdf"
        one.write_bytes(pdf_bytes(1))
        two.write_bytes(pdf_bytes(2))
        self.assertEqual(pdf_page_count(one), 1)
        self.assertTrue(is_one_page(one))
        self.assertEqual(pdf_page_count(two), 2)
        self.assertFalse(is_one_page(two))


class SubmitPdfName(unittest.TestCase):
    def test_profile_name_is_first_last_resume(self) -> None:
        name = submit_pdf_name()
        self.assertRegex(name, r"^[A-Za-z0-9]+_[A-Za-z0-9]+_resume\.pdf$")
        self.assertEqual(
            submit_pdf_name({"first_name": "Joseph", "last_name": "Yu"}),
            "Joseph_Yu_resume.pdf",
        )
        self.assertEqual(
            submit_pdf_name({"first_name": "Alex", "last_name": "Rivera"}),
            "Alex_Rivera_resume.pdf",
        )

    def test_promote_copies_latexmk_output(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name)
        (folder / "resume.pdf").write_bytes(b"%PDF-latexmk")
        dest = submit_pdf_path(folder, promote=True)
        self.assertEqual(dest.name, submit_pdf_name())
        self.assertTrue(dest.is_file())
        self.assertEqual(dest.read_bytes(), b"%PDF-latexmk")
        self.assertTrue((folder / "resume.pdf").is_file())


class ResumeReady(unittest.TestCase):
    def test_missing_pdf_is_unready(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name)
        (folder / "resume.tex").write_text("%\n", encoding="utf-8")
        ok, issues = resume_ready(folder)
        self.assertFalse(ok)
        self.assertTrue(any("missing" in i for i in issues))

    def test_one_page_pdf_without_tex_is_ready(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name)
        (folder / "resume.pdf").write_bytes(pdf_bytes(1))
        ok, issues = resume_ready(folder)
        self.assertTrue(ok, issues)
        self.assertEqual(issues, [])

    def test_two_page_pdf_is_unready(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name)
        (folder / "resume.pdf").write_bytes(pdf_bytes(2))
        ok, _ = resume_ready(folder)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
