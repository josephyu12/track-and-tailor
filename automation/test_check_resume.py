#!/usr/bin/env python3
"""Heading/date format checks for tailored resumes."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / ".cursor" / "skills" / "tailor-resume" / "scripts"
sys.path.insert(0, str(SCRIPTS))
from check_resume import check_tex, gpu_skus, heading_budget, latex_to_visible  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MASTER = (ROOT / "master" / "resume.example.tex").read_text(encoding="utf-8")

EXAMPLE = r"""
\resumeProjectHeading
    {\textbf{Example Labs} $|$ \emph{Python, AWS, Batch Computing\iftoggle{showprojectgpu}{, A100, L40S}{}}}{Jan. 2025 -- Present}
    \resumeItemListStart
      \resumeItem{Trained ranking models with CUDA GPU batch on \textbf{A100}/\textbf{L40S}}
    \resumeItemListEnd
"""


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


if __name__ == "__main__":
    unittest.main()
