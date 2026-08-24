#!/usr/bin/env python3
"""Formatting checks for a tailored resume.tex (and its PDF if present).

Catches the two failures that shove a project date into the italic stack:
1. Left-hand project heading longer than the master (tabular* cannot wrap).
2. GPU SKUs (A100 / L40S / A10) in both the italic heading and that
   project's bullets — including via showprojectgpu.

Also checks PDF page count and smashed date text (L40SDec.) when a PDF exists.

Usage (from repo root):
  python3 .cursor/skills/tailor-resume/scripts/check_resume.py applications/some-slug
  python3 .cursor/skills/tailor-resume/scripts/check_resume.py applications/some-slug/resume.tex
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import zlib
from pathlib import Path

GPU_SKU_RE = re.compile(r"(?<![A-Za-z0-9])(A100|L40S|A10)(?![A-Za-z0-9])", re.I)
MONTH_SMASH_RE = re.compile(
    r"[A-Za-z0-9](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.",
)
TOGGLE_SET_RE = re.compile(r"\\toggle(true|false)\{(\w+)\}")
NEWTOGGLE_RE = re.compile(r"\\newtoggle\{(\w+)\}")
IFTOGGLE_RE = re.compile(r"\\iftoggle\{(\w+)\}")
HEADING_RE = re.compile(r"\\resumeProjectHeading\b")
ITEM_RE = re.compile(r"\\resumeItem\s*\{")
LIST_END_RE = re.compile(r"\\resume(?:Item|SubHeading)ListEnd\b")
ONEARG_CMD_RE = re.compile(
    r"\\(?:textbf|emph|textit|textrm|textup|text|small|normalsize)\s*\{"
)
FALLBACK_HEADING_BUDGET = 88


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "master" / "resume.tex").exists():
            return parent
    return here.parents[4]


def strip_comments(tex: str) -> str:
    out: list[str] = []
    for line in tex.splitlines():
        cut = len(line)
        i = 0
        while i < len(line):
            if line[i] == "%" and (i == 0 or line[i - 1] != "\\"):
                cut = i
                break
            i += 1
        out.append(line[:cut])
    return "\n".join(out)


def parse_toggles(tex: str) -> dict[str, bool]:
    flags = {m.group(1): False for m in NEWTOGGLE_RE.finditer(tex)}
    for m in TOGGLE_SET_RE.finditer(tex):
        flags[m.group(2)] = m.group(1) == "true"
    return flags


def skip_ws(s: str, i: int) -> int:
    n = len(s)
    while i < n and s[i].isspace():
        i += 1
    return i


def grab_brace(s: str, i: int) -> tuple[str, int]:
    i = skip_ws(s, i)
    if i >= len(s) or s[i] != "{":
        raise ValueError(f"expected '{{' at {i}")
    depth = 0
    start = i + 1
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start:i], i + 1
        i += 1
    raise ValueError("unbalanced brace")


def expand_toggles(tex: str, flags: dict[str, bool] | None = None) -> str:
    flags = flags if flags is not None else parse_toggles(tex)
    for _ in range(80):
        m = IFTOGGLE_RE.search(tex)
        if not m:
            return tex
        yes, after_yes = grab_brace(tex, m.end())
        no, after_no = grab_brace(tex, after_yes)
        chosen = yes if flags.get(m.group(1), False) else no
        tex = tex[: m.start()] + chosen + tex[after_no:]
    raise ValueError("iftoggle expansion did not terminate")


def latex_to_visible(s: str) -> str:
    s = s.replace(r"$|$", "|").replace(r"\textbar", "|")
    s = s.replace(r"\%", "%").replace(r"\&", "&").replace(r"\_", "_")
    s = s.replace("~", " ").replace(r"\,", " ").replace("--", "–")
    for _ in range(40):
        m = ONEARG_CMD_RE.search(s)
        if not m:
            break
        inner, end = grab_brace(s, m.end() - 1)
        s = s[: m.start()] + inner + s[end:]
    s = re.sub(r"\\[a-zA-Z]+\*?\s*", "", s)
    s = s.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", s).strip()


def gpu_skus(text: str) -> set[str]:
    return {m.group(1).upper() for m in GPU_SKU_RE.finditer(text)}


def iter_project_blocks(expanded: str) -> list[tuple[str, str, list[str]]]:
    blocks: list[tuple[str, str, list[str]]] = []
    for m in HEADING_RE.finditer(expanded):
        rest = expanded[m.end() :]
        if rest.lstrip().startswith("["):
            continue
        try:
            left, after_left = grab_brace(expanded, m.end())
            date, after_date = grab_brace(expanded, after_left)
        except ValueError:
            continue
        items: list[str] = []
        cursor = after_date
        while True:
            nxt_head = HEADING_RE.search(expanded, cursor)
            nxt_item = ITEM_RE.search(expanded, cursor)
            nxt_end = LIST_END_RE.search(expanded, cursor)
            limit = len(expanded)
            for nxt in (nxt_head, nxt_end):
                if nxt:
                    limit = min(limit, nxt.start())
            if not nxt_item or nxt_item.start() >= limit:
                break
            body, cursor = grab_brace(expanded, nxt_item.end() - 1)
            items.append(body)
        blocks.append((left, date, items))
    return blocks


def heading_budget(master_tex: str | None) -> int:
    if not master_tex:
        return FALLBACK_HEADING_BUDGET
    lengths = [
        len(latex_to_visible(left))
        for left, _date, _items in iter_project_blocks(expand_toggles(strip_comments(master_tex)))
        if latex_to_visible(left)
    ]
    return max(lengths) if lengths else FALLBACK_HEADING_BUDGET


def check_tex(tex: str, *, budget: int | None = None, master_tex: str | None = None) -> list[str]:
    issues: list[str] = []
    cleaned = strip_comments(tex)
    expanded = expand_toggles(cleaned)
    if budget is None:
        budget = heading_budget(master_tex)
    for left, date, items in iter_project_blocks(expanded):
        heading = latex_to_visible(left)
        if not heading:
            continue
        n = len(heading)
        if n > budget:
            issues.append(
                f"project heading {n} chars (budget {budget}); date will collide: {heading}"
            )
        heading_gpus = gpu_skus(heading)
        if not heading_gpus:
            continue
        bullet_text = latex_to_visible(" ".join(items))
        overlap = heading_gpus & gpu_skus(bullet_text)
        if overlap:
            skus = ", ".join(sorted(overlap))
            issues.append(
                f"{skus} in italic heading and bullets; drop them from the heading "
                f"(leave showprojectgpu off): {heading}"
            )
    return issues


def _run_text(cmd: list[str]) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout if proc.returncode == 0 else ""


def _page_markers(blob: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page(?!s)", blob)) + len(
        re.findall(rb"/Type/Page(?!s)", blob)
    )


def pdf_page_count(pdf: Path) -> int | None:
    info = _run_text(["pdfinfo", str(pdf)])
    m = re.search(r"^Pages:\s*(\d+)", info, re.M)
    if m:
        return int(m.group(1))
    mdls = _run_text(["mdls", "-name", "kMDItemNumberOfPages", "-raw", str(pdf)])
    if mdls.strip().isdigit():
        return int(mdls.strip())
    data = pdf.read_bytes()
    n = _page_markers(data)
    if n:
        return n
    inflated = 0
    for m in re.finditer(rb"stream\r?\n", data):
        start = m.end()
        end = data.find(b"endstream", start)
        if end < 0:
            continue
        blob = data[start:end].rstrip(b"\r\n")
        for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
            try:
                out = zlib.decompress(blob, wbits)
            except zlib.error:
                continue
            inflated += _page_markers(out)
            break
    if inflated:
        return inflated
    counts = [int(c) for c in re.findall(rb"/Count\s+(\d+)", data)]
    return max(counts) if counts else None


def pdf_text(pdf: Path) -> str:
    for args in (["pdftotext", "-layout", str(pdf), "-"], ["pdftotext", str(pdf), "-"]):
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=10)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        if proc.returncode == 0:
            return proc.stdout
    return ""


def check_pdf(pdf: Path) -> list[str]:
    issues: list[str] = []
    pages = pdf_page_count(pdf)
    if pages is None:
        issues.append(f"could not read page count from {pdf.name}")
    elif pages != 1:
        issues.append(f"PDF is {pages} pages; must be exactly 1")
    text = pdf_text(pdf)
    if text:
        smash = MONTH_SMASH_RE.search(text.replace("\n", ""))
        if smash:
            issues.append(
                f"date smashed into heading in PDF text ({smash.group(0)!r}); "
                "shorten the italic project stack"
            )
    log = pdf.with_name("resume.log")
    if log.exists():
        overfull = re.findall(
            r"Overfull \\hbox \(([\d.]+)pt too wide\)",
            log.read_text(encoding="utf-8", errors="replace"),
        )
        bad = [float(x) for x in overfull if float(x) >= 8.0]
        if bad:
            issues.append(
                f"Overfull hbox {max(bad):.1f}pt; a heading is colliding with a date"
            )
    return issues


def resolve_targets(path: Path) -> tuple[Path, Path | None]:
    if path.is_dir():
        tex = path / "resume.tex"
        pdf = path / "resume.pdf"
        if not pdf.exists():
            pdf = path / "resume.pdf"
        return tex, pdf if pdf.exists() else None
    if path.suffix.lower() == ".tex":
        return path, None
    raise SystemExit(f"not a resume folder or .tex file: {path}")


def check_path(path: Path, *, require_pdf: bool = False) -> list[str]:
    tex_path, pdf_path = resolve_targets(path)
    if not tex_path.exists():
        return [f"missing {tex_path}"]
    master = repo_root() / "master" / "resume.tex"
    master_tex = master.read_text(encoding="utf-8") if master.exists() else None
    issues = check_tex(
        tex_path.read_text(encoding="utf-8"),
        master_tex=master_tex,
    )
    if pdf_path is not None:
        issues.extend(check_pdf(pdf_path))
    elif require_pdf:
        issues.append(f"missing resume.pdf in {path}")
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check tailored resume heading/date formatting")
    parser.add_argument("path", help="application folder or resume.tex")
    parser.add_argument(
        "--require-pdf",
        action="store_true",
        help="fail if resume.pdf is missing (use after compile)",
    )
    args = parser.parse_args(argv)
    path = Path(args.path)
    require_pdf = args.require_pdf or path.is_dir()
    issues = check_path(path, require_pdf=require_pdf)
    if not issues:
        print("OK")
        return 0
    print("FAIL")
    for issue in issues:
        print(f"- {issue}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
