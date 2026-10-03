#!/usr/bin/env python3
"""Formatting checks for a tailored resume.tex (and its PDF if present).

Catches the two failures that shove a project date into the italic stack:
1. Left-hand project heading longer than the master (tabular* cannot wrap).
2. GPU SKUs (A100 / L40S / A10) in both the italic heading and that
   project's bullets — including via showprojectgpu.

Also checks PDF page count, smashed date text (L40SDec.), and wrapped
lines that leave only a word or two on the next row.

Usage (from repo root):
  python3 .cursor/skills/tailor-resume/scripts/check_resume.py applications/some-slug
  python3 .cursor/skills/tailor-resume/scripts/check_resume.py applications/some-slug/resume.tex
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import zlib
from pathlib import Path
from typing import NamedTuple

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
# Ragged-right lines that actually wrapped still end a bit short of the margin.
MARGIN_SLACK_PT = 48.0
# A continuation narrower than this is a word or two, not a used line.
STUB_MAX_WIDTH_PT = 150.0
NEW_ITEM_RE = re.compile(r"^\s*[•·∙●▪‣]\s*")


class VisualLine(NamedTuple):
    y: float
    x0: float
    x1: float
    size: float
    text: str


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "master" / "resume.tex").exists():
            return parent
        if (parent / "master" / "resume.example.tex").exists():
            return parent
    return here.parents[4]


def load_profile() -> dict:
    path = repo_root() / ".cursor" / "skills" / "tailor-resume" / "profile.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _name_token(value: object, fallback: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "").strip())
    text = re.sub(r"_+", "_", text).strip("_")
    return text or fallback


def submit_pdf_name(profile: dict | None = None) -> str:
    """Submit PDF basename: First_Last_resume.pdf from profile.json."""
    data = profile if profile is not None else load_profile()
    first = _name_token(data.get("first_name"), "First")
    last = _name_token(data.get("last_name"), "Last")
    return f"{first}_{last}_resume.pdf"


def submit_pdf_path(folder: Path, *, promote: bool = False) -> Path:
    """Preferred submit PDF in an application folder.

    Prefers First_Last_resume.pdf. Falls back to latexmk's resume.pdf.
    If promote is true and only resume.pdf exists, copy it to the named file.
    """
    folder = Path(folder)
    named = folder / submit_pdf_name()
    legacy = folder / "resume.pdf"
    if named.is_file():
        return named
    if legacy.is_file():
        if promote:
            shutil.copy2(legacy, named)
            return named
        return legacy
    return named


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
    return len(re.findall(rb"/Type\s*/Page(?!s)", blob))


def _pdf_page_count_local(data: bytes) -> int | None:
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


def pdf_page_count(pdf: Path) -> int | None:
    """Page count from the file bytes, then pdfinfo if the bytes have no markers."""
    try:
        local = _pdf_page_count_local(pdf.read_bytes())
    except OSError:
        local = None
    if local:
        return local
    info = _run_text(["pdfinfo", str(pdf)])
    m = re.search(r"^Pages:\s*(\d+)", info, re.M)
    if m:
        return int(m.group(1))
    mdls = _run_text(["mdls", "-name", "kMDItemNumberOfPages", "-raw", str(pdf)])
    if mdls.strip().isdigit():
        return int(mdls.strip())
    return None


def pdf_text(pdf: Path) -> str:
    for args in (["pdftotext", "-layout", str(pdf), "-"], ["pdftotext", str(pdf), "-"]):
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=10)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        if proc.returncode == 0:
            return proc.stdout
    return ""


def is_one_page(pdf: Path) -> bool:
    return pdf_page_count(pdf) == 1


def short_last_lines(lines: list[VisualLine]) -> list[str]:
    """Flag a wrap whose last line is only a word or two.

    A full line followed by a hanging indent, or by another skills/coursework
    row at the same left edge, is a wasted row when that next line is narrower
    than STUB_MAX_WIDTH_PT. New bullets (they start with a glyph) and the
    right-hand date column are not wraps.
    """
    if len(lines) < 2:
        return []
    right = max(line.x1 for line in lines)
    issues: list[str] = []
    ordered = sorted(lines, key=lambda ln: (ln.y, ln.x0))
    for prev, cur in zip(ordered, ordered[1:]):
        if cur.y < prev.y + 2:
            continue
        if abs(cur.size - prev.size) > 1.25:
            continue
        if NEW_ITEM_RE.match(cur.text):
            continue
        if cur.x0 > right - 180:
            continue
        if right - prev.x1 > MARGIN_SLACK_PT:
            continue
        if cur.x0 < prev.x0 - 2 or cur.x0 > prev.x0 + 16:
            continue
        width = cur.x1 - cur.x0
        if width >= STUB_MAX_WIDTH_PT:
            continue
        words = cur.text.split()
        n = len(words)
        label = "1 word" if n == 1 else f"{n} words"
        snippet = cur.text.strip()[:90]
        issues.append(
            f"short last line ({label}, {width:.0f}pt) after a full line; "
            f"cut so it fits on the line above, or add real content so the line is nearly full: {snippet}"
        )
    return issues


def _import_pymupdf():
    try:
        import pymupdf
    except ImportError:
        pymupdf = None
    if pymupdf is None:
        try:
            import fitz as pymupdf
        except ImportError:
            return None
    return pymupdf


def visual_lines(pdf: Path) -> list[VisualLine] | None:
    """Text lines with positions. None when PyMuPDF is missing or the file is not a PDF."""
    pymupdf = _import_pymupdf()
    if pymupdf is None:
        return None
    try:
        doc = pymupdf.open(pdf)
    except Exception:
        return None
    lines: list[VisualLine] = []
    try:
        for page in doc:
            data = page.get_text("dict")
            for block in data.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    spans = line.get("spans") or []
                    text = "".join(span.get("text", "") for span in spans).strip()
                    if not text:
                        continue
                    x0, y0, x1, _y1 = line["bbox"]
                    size = max((float(span.get("size", 0)) for span in spans), default=0.0)
                    lines.append(VisualLine(float(y0), float(x0), float(x1), size, text))
    except Exception:
        return None
    finally:
        doc.close()
    return lines


def check_pdf(pdf: Path) -> list[str]:
    issues: list[str] = []
    pages = pdf_page_count(pdf)
    if pages is None:
        issues.append(f"could not read page count from {pdf.name}")
    elif pages != 1:
        issues.append(f"PDF is {pages} pages; must be exactly 1")
    positioned = visual_lines(pdf)
    if positioned:
        issues.extend(short_last_lines(positioned))
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
        pdf = submit_pdf_path(path, promote=True)
        return tex, pdf if pdf.is_file() else None
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
        issues.append(f"missing {submit_pdf_name()} in {path}")
    return issues


def resume_ready(folder: Path) -> tuple[bool, list[str]]:
    """True when the folder has a one-page submit PDF that passes check_resume.

    A PDF without resume.tex is judged on page count only (test fixtures).
    """
    folder = Path(folder)
    if not folder.is_dir():
        return False, [f"missing {folder}"]
    pdf = submit_pdf_path(folder)
    if not pdf.is_file():
        return False, [f"missing {submit_pdf_name()} in {folder}"]
    if (folder / "resume.tex").is_file():
        issues = check_path(folder, require_pdf=True)
        return (not issues, issues)
    issues = check_pdf(pdf)
    return (not issues, issues)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check tailored resume heading/date formatting")
    parser.add_argument("path", help="application folder or resume.tex")
    parser.add_argument(
        "--require-pdf",
        action="store_true",
        help="fail if First_Last_resume.pdf is missing (use after compile)",
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
