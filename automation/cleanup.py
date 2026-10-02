#!/usr/bin/env python3
"""Keep application folders from growing without bound.

Policy (see config retain_*):
- Always strip LaTeX aux files and extra PDFs; never delete First_Last_resume.pdf
- Promote latexmk's resume.pdf to First_Last_resume.pdf (profile.json names)
- Delete empty leftover folders (no job.md and no submit PDF)
- Keep failed-tailor folders that still have job.md so retry/dashboard do not 404
- Delete folders older than retain_days unless they contain `.keep`
- If unpinned folders still exceed retain_max_apps, drop oldest complete
  one-page resumes. Folders that still need a passing resume (job.md without
  a check_resume-OK PDF) and `.keep` never count toward the cap.
- Rotate reports and daily.log
- Compact seeded rows in seen.json
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
APPS = ROOT / "applications"
REPORTS = ROOT / "automation" / "reports"
LOGS = ROOT / "automation" / "logs"
SEEN = ROOT / "automation" / "state" / "seen.json"
SCRAPE = ROOT / ".cursor" / "skills" / "tailor-resume" / "scripts"

sys.path.insert(0, str(SCRAPE))
from check_resume import resume_ready, submit_pdf_name, submit_pdf_path  # noqa: E402

AUX_SUFFIXES = {".aux", ".log", ".out", ".fdb_latexmk", ".fls", ".synctex.gz", ".toc"}
KEEP_NAME = ".keep"


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def tidy_folder(folder: Path) -> list[str]:
    """Remove compile junk and extra PDFs. Keep First_Last_resume.pdf + sources."""
    removed: list[str] = []
    if not folder.is_dir():
        return removed
    named = folder / submit_pdf_name()
    legacy = folder / "resume.pdf"
    if not named.is_file() and legacy.is_file():
        shutil.copy2(legacy, named)
    submit = named if named.is_file() else legacy
    for path in list(folder.iterdir()):
        if not path.is_file():
            continue
        if path.suffix in AUX_SUFFIXES or path.name == ".DS_Store":
            path.unlink(missing_ok=True)
            removed.append(path.name)
            continue
        if (
            path.suffix.lower() == ".pdf"
            and path.name != submit.name
            and submit.is_file()
        ):
            path.unlink(missing_ok=True)
            removed.append(path.name)
    return removed


def keep_unready_from_cap(folder: Path) -> bool:
    """True when the folder still needs a passing one-page resume (do not cap-delete)."""
    if not (folder / "job.md").is_file():
        return False
    ready, _ = resume_ready(folder)
    return not ready


def is_stub(folder: Path) -> bool:
    """True only for empty leftovers, not for a failed tailor that still has job.md.

    Cleanup used to delete job.md-only folders. After a hung agent those folders
    are older than the 180s grace window, so the listing vanished from disk
    while seen.json still pointed at it (dashboard: Application not found).
    """
    if (folder / KEEP_NAME).exists():
        return False
    if submit_pdf_path(folder).is_file():
        return False
    if (folder / "job.md").is_file():
        return False
    names = {p.name for p in folder.iterdir() if p.is_file()}
    return names <= {"application_questions.md", "resume.tex", ".DS_Store"}


def prune_applications(
    retain_days: int,
    retain_max: int,
    now: datetime | None = None,
    log: Callable[[str], None] | None = None,
) -> dict[str, int]:
    now = now or datetime.now()
    cutoff = now.timestamp() - retain_days * 86400
    stats = {"tidied": 0, "stubs": 0, "expired": 0, "capped": 0}
    if not APPS.is_dir():
        return stats

    folders = [p for p in APPS.iterdir() if p.is_dir() and not p.name.startswith(".")]
    aged: list[tuple[float, Path]] = []
    now_ts = now.timestamp()
    for folder in folders:
        age_mtime = _mtime(folder)
        if now_ts - age_mtime < 180:
            aged.append((age_mtime, folder))
            continue
        n = len(tidy_folder(folder))
        if n:
            stats["tidied"] += 1
        if is_stub(folder):
            _rmtree(folder)
            stats["stubs"] += 1
            continue
        if age_mtime < cutoff and not (folder / KEEP_NAME).exists():
            _rmtree(folder)
            stats["expired"] += 1
            continue
        aged.append((age_mtime, folder))

    aged.sort(key=lambda pair: pair[0])
    kept = [p for _, p in aged]
    while True:
        victims = [
            p
            for p in kept
            if not (p / KEEP_NAME).exists() and not keep_unready_from_cap(p)
        ]
        if len(victims) <= retain_max:
            break
        folder = victims[0]
        _rmtree(folder)
        kept.remove(folder)
        stats["capped"] += 1

    if log:
        log(
            "cleanup applications: "
            f"tidied {stats['tidied']}, stubs {stats['stubs']}, "
            f"expired {stats['expired']}, capped {stats['capped']}, kept {len(kept)}"
        )
    return stats


def prune_reports(retain_days: int, log: Callable[[str], None] | None = None) -> int:
    if not REPORTS.is_dir():
        return 0
    cutoff = datetime.now().timestamp() - retain_days * 86400
    n = 0
    for path in REPORTS.iterdir():
        if path.suffix in {".md", ".html"} and _mtime(path) < cutoff:
            path.unlink(missing_ok=True)
            n += 1
    if log and n:
        log(f"cleanup reports: removed {n}")
    return n


def prune_log(max_bytes: int = 200_000, log: Callable[[str], None] | None = None) -> None:
    path = LOGS / "daily.log"
    if not path.exists() or path.stat().st_size <= max_bytes:
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    keep = lines[-800:]
    path.write_text("\n".join(keep) + "\n", encoding="utf-8")
    if log:
        log(f"cleanup log: truncated to {len(keep)} lines")


def compact_seen(log: Callable[[str], None] | None = None) -> None:
    if not SEEN.exists():
        return
    data = json.loads(SEEN.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return
    changed = False
    compact: dict[str, Any] = {}
    for key, rec in data.items():
        if isinstance(rec, dict) and rec.get("status") == "seeded":
            compact[key] = {"status": "seeded"}
            if rec.keys() - {"status"}:
                changed = True
        else:
            compact[key] = rec
    if changed:
        tmp = SEEN.with_suffix(".tmp")
        tmp.write_text(json.dumps(compact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(SEEN)
        if log:
            log(f"cleanup seen.json: compacted {len(compact)} ids")


def _rmtree(folder: Path) -> None:
    for path in sorted(folder.rglob("*"), reverse=True):
        if path.is_file() or path.is_symlink():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            path.rmdir()
    folder.rmdir()


def run_cleanup(cfg: dict[str, Any], log: Callable[[str], None] | None = None) -> dict[str, int]:
    retain_days = int(cfg.get("retain_days") or 21)
    retain_max = int(cfg.get("retain_max_apps") or 400)
    report_days = int(cfg.get("retain_reports_days") or 14)
    stats = prune_applications(retain_days, retain_max, log=log)
    prune_reports(report_days, log=log)
    prune_log(log=log)
    compact_seen(log=log)
    return stats


if __name__ == "__main__":
    cfg_path = Path(__file__).resolve().parent / "config.json"
    cfg = json.loads(cfg_path.read_text())
    run_cleanup(cfg, log=print)
