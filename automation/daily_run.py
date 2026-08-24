#!/usr/bin/env python3
"""Daily watcher: new SimplifyJobs Summer 2027 listings → tailored resumes."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from http.client import IncompleteRead
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AUTO = Path(__file__).resolve().parent
STATE_DIR = AUTO / "state"
LOGS_DIR = AUTO / "logs"
REPORTS_DIR = AUTO / "reports"
CONFIG_PATH = AUTO / "config.json"
SEEN_PATH = STATE_DIR / "seen.json"
QUEUE_PATH = STATE_DIR / "queue.json"
LOCK_PATH = STATE_DIR / "lock"
SCRAPE_DIR = ROOT / ".cursor" / "skills" / "tailor-resume" / "scripts"
CHECK_SCRIPT = SCRAPE_DIR / "check_resume.py"

sys.path.insert(0, str(SCRAPE_DIR))
sys.path.insert(0, str(AUTO))
from scrape_jd import MIN_JD_CHARS, scrape_one  # noqa: E402
from application_questions import (  # noqa: E402
    questions_look_real,
    questions_summary,
    render_answers_md,
)
from report import collect_today, write_daily_report  # noqa: E402
from fit import evaluate_listing  # noqa: E402
from cleanup import run_cleanup, tidy_folder  # noqa: E402
from dedupe import index_from_seen  # noqa: E402

UA = "InternshipWatch/1.0"
RETRY_STATUSES = frozenset({"tailor_failed", "scrape_failed"})


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open() as f:
        return json.load(f)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open() as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.replace(path)


def log(msg: str) -> None:
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with (LOGS_DIR / "daily.log").open("a") as f:
        f.write(line + "\n")


def fetch_listings(url: str, attempts: int = 4) -> list[dict[str, Any]]:
    last: BaseException | None = None
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Connection": "close",
        },
    )
    for attempt in range(max(1, attempts)):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                try:
                    raw = resp.read()
                except IncompleteRead as e:
                    raw = bytes(e.partial or b"")
                    if len(raw) < 2048:
                        raise
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, list):
                raise RuntimeError("listings.json was not a list")
            return data
        except (urllib.error.URLError, IncompleteRead, TimeoutError, json.JSONDecodeError, OSError) as e:
            last = e
            if attempt + 1 < attempts:
                time.sleep(1.2 * (attempt + 1))
                continue
            raise
    raise last or RuntimeError("listings fetch failed")


def is_advanced_only(listing: dict[str, Any]) -> bool:
    title = str(listing.get("title") or "")
    if "🎓" in title or re.search(r"\b(ph\.?d|master'?s only)\b", title, re.I):
        return True
    degrees = listing.get("degrees") or []
    if not degrees:
        return False
    undergrad = any("bachelor" in str(d).lower() for d in degrees)
    return not undergrad


def matches(listing: dict[str, Any], cfg: dict[str, Any]) -> bool:
    if not listing.get("active") or not listing.get("is_visible"):
        return False
    cats = set(cfg.get("categories") or [])
    if str(listing.get("category") or "") not in cats:
        return False
    term = cfg.get("require_term") or "Summer 2027"
    terms = " ".join(listing.get("terms") or [])
    if term not in terms:
        return False
    if cfg.get("skip_advanced_degree_only") and is_advanced_only(listing):
        return False
    title = str(listing.get("title") or "")
    for needle in cfg.get("title_exclude") or []:
        if needle.lower() in title.lower():
            return False
    url = str(listing.get("url") or "")
    if not url.startswith("http"):
        return False
    return True


def slugify(company: str, role: str, listing_id: str) -> str:
    raw = f"{company}-{role}".lower()
    raw = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    raw = re.sub(r"-{2,}", "-", raw)[:72].strip("-")
    if not raw:
        raw = listing_id[:12]
    dest = ROOT / "applications" / raw
    if dest.exists():
        return f"{raw}-{listing_id[:8]}"
    return raw


def which(name: str) -> str | None:
    extra = [
        Path.home() / ".local" / "bin",
        Path("/Applications/Cursor.app/Contents/Resources/app/bin"),
        Path("/Library/TeX/texbin"),
        Path("/opt/homebrew/bin"),
        Path("/usr/local/bin"),
    ]
    for folder in list(Path(p) for p in os.environ.get("PATH", "").split(":") if p) + extra:
        cand = folder / name
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    return None


def _job_md_has_body(path: Path) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    marker = "## Job description"
    idx = text.find(marker)
    body = text[idx + len(marker) :] if idx >= 0 else text
    return len(body.strip()) >= MIN_JD_CHARS


def write_job_md(
    slug: str,
    listing: dict[str, Any],
    scraped: dict[str, Any],
    copy_master: bool = True,
) -> Path:
    company = scraped.get("company") or listing.get("company_name") or "Unknown"
    role = scraped.get("role") or listing.get("title") or "Intern"
    url = listing.get("url") or ""
    loc = scraped.get("location") or ", ".join(listing.get("locations") or [])
    jd = (scraped.get("jd_text") or "").strip()
    if not jd:
        jd = f"(JD scrape failed: {scraped.get('error') or 'unknown'})\n\nApply: {url}\n"
    questions = scraped.get("questions") or []
    folder = ROOT / "applications" / slug
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "job.md"
    path.write_text(
        f"# {company} — {role}\n\n"
        f"- Date: {date.today().isoformat()}\n"
        f"- Source: {url}\n"
        f"- Slug: {slug}\n"
        f"- Location: {loc}\n"
        f"- Listing id: {listing.get('id')}\n"
        f"- Category: {listing.get('category')}\n"
        f"- Watcher: SimplifyJobs/Summer2027-Internships\n"
        f"- Form questions: {len(questions)}\n\n"
        f"## Job description\n\n{jd}\n\n"
        f"## Application questions\n\n{questions_summary(questions)}\n\n"
        f"## Tailoring notes\n\n(pending daily watcher)\n",
        encoding="utf-8",
    )
    answers = folder / "application_questions.md"
    answers.write_text(
        render_answers_md(str(company), str(role), str(url), questions),
        encoding="utf-8",
    )
    master = ROOT / "master" / "resume.tex"
    dest_tex = folder / "resume.tex"
    if copy_master and not dest_tex.exists():
        shutil.copy(master, dest_tex)
    return path


def _is_executable(path: str) -> bool:
    p = Path(path)
    return p.is_file() and os.access(p, os.X_OK)


def cursor_agent_argv() -> list[str] | None:
    """Cursor Agent CLI: `cursor-agent` / `agent`, else `cursor agent`.

    Ignore CURSOR_AGENT=1 (Cursor IDE sets that flag; it is not a binary).
    """
    override = os.environ.get("CURSOR_AGENT")
    if override and _is_executable(override):
        return [override]
    for name in ("cursor-agent", "agent"):
        found = which(name)
        if found:
            return [found]
    cursor = which("cursor")
    if cursor:
        return [cursor, "agent"]
    return None


def reset_resume_tex(slug: str) -> None:
    dest = ROOT / "applications" / slug
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "master" / "resume.tex", dest / "resume.tex")


def _kill_process_group(proc: subprocess.Popen[Any]) -> None:
    """Kill cursor-agent and its worker-server children.

    subprocess.run(timeout=) only signals the direct child. The CLI's
    grandchild keeps stdout open, so communicate() hangs past the timeout
    and the daily run never reaches later listings.
    """
    if proc.poll() is not None:
        return
    try:
        if proc.pid and os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
            return
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        proc.kill()
    except ProcessLookupError:
        pass


def _decode_pipe(raw: str | bytes | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "replace")
    return raw


def run_agent_cmd(
    cmd: list[str],
    timeout: int,
    cwd: str,
    env: dict[str, str] | None = None,
) -> tuple[int | None, str, bool]:
    """Run the agent CLI. Returns (returncode, combined output, timed_out)."""
    popen_kw: dict[str, Any] = {
        "cwd": cwd,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "env": env,
    }
    if os.name == "posix":
        popen_kw["start_new_session"] = True
    proc = subprocess.Popen(cmd, **popen_kw)
    timed_out = False
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as first:
        timed_out = True
        _kill_process_group(proc)
        try:
            out, err = proc.communicate(timeout=8)
        except subprocess.TimeoutExpired as second:
            _kill_process_group(proc)
            out = second.stdout if second.stdout is not None else first.stdout
            err = second.stderr if second.stderr is not None else first.stderr
    combined = (_decode_pipe(out) + ("\n" + _decode_pipe(err) if err else "")).strip()
    return proc.poll(), combined, timed_out


def format_check_resume(slug: str) -> tuple[bool, str]:
    folder = ROOT / "applications" / slug
    proc = subprocess.run(
        [sys.executable, str(CHECK_SCRIPT), str(folder)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    msg = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode == 0, msg


def tailor_with_cursor(
    slug: str,
    listing: dict[str, Any],
    timeout: int,
    *,
    do_resume: bool = True,
    do_answers: bool = True,
) -> tuple[bool, str]:
    if not do_resume and not do_answers:
        return False, "nothing to generate"
    argv = cursor_agent_argv()
    if not argv:
        return False, (
            "Cursor Agent CLI not found. Install it with: "
            "curl https://cursor.com/install -fsS | bash"
        )
    folder = f"applications/{slug}"
    if do_resume:
        reset_resume_tex(slug)
    tasks = []
    if do_resume:
        tasks.append(
            f"Copy of master is at {folder}/resume.tex (already reset). Tailor that resume.tex only. "
            "Compile with latexmk -pdf -interaction=nonstopmode in that folder, then "
            "cp resume.pdf resume.pdf. Then run python3 .cursor/skills/tailor-resume/scripts/check_resume.py "
            f"{folder} and fix until it prints OK (heading/date collision, GPU names duplicated in heading and bullets, page count). "
            "Then latexmk -C && rm -f resume.pdf. Keep exactly one FULL page: "
            "Keep high school on by default (master already fills one page with it). Drop HS only if the PDF overflows to two pages after keyword edits. "
            "If you drop high school, fill the space from master/bank.md (extra bullets, courses, JD keywords). "
            "A short sparse one-pager is a failed tailor. Match as many true JD keywords as possible."
        )
    if do_answers:
        tasks.append(
            f"Rewrite {folder}/application_questions.md with every apply-form question you can get "
            "from the posting URL and job.md. If that file still says none found, run "
            "python3 .cursor/skills/tailor-resume/scripts/harvest_apply_form.py on the posting URL. "
            "That helper clicks Start Application / Apply / Apply Manually, then reads the form. "
            "Never click Submit, Send application, or Next through the form. "
            "If you browse by hand, use $B wait --load (not --networkidle), then $B forms and $B html. "
            "Login wall: list only visible fields. CAPTCHA: $B handoff. "
            "Fill each answer from master/resume.tex, master/bank.md, "
            "and .cursor/skills/tailor-resume/profile.json only. Replace DRAFT / Needs user only when "
            "those files have the fact; otherwise leave Needs user. Never invent facts. "
            "Follow .cursor/skills/tailor-resume/writing.md for cover letters and essays: creative, "
            "novel-like, off-resume material, no citizenship/relocation in letters, no em dashes, "
            "avoid colons in prose, points must flow (not a three-job sandwich). "
            "Do not skip questions even if the first HTTP scrape found none."
        )
    if do_resume and not do_answers:
        tasks.append(f"Do not rewrite {folder}/application_questions.md.")
    if do_answers and not do_resume:
        tasks.append(f"Do not edit {folder}/resume.tex and do not compile a PDF.")
    prompt = f"""Follow .cursor/skills/tailor-resume/SKILL.md exactly. Do not edit master/resume.tex.

Company: {listing.get('company_name')}
Role: {listing.get('title')}
URL: {listing.get('url')}
Slug: {slug}

The JD is already at {folder}/job.md.
Keep Education at the top. Keep jobs and projects reverse chronological. You may reorder the Technical Skills, Experience, and Projects sections as whole blocks.
If this role is AI Engineer, ML Engineer, LLM, GenAI, or similar, apply the skill's AI / ML pack in full (heavy). Do not leave the master default.
{chr(10).join('- ' + t for t in tasks)}
Never invent facts.
Reply with the changelog format from the skill, nothing else.
"""
    cmd = [
        *argv,
        "-p",
        "--force",
        "--trust",
        "--sandbox",
        "disabled",
        "--workspace",
        str(ROOT),
        "--output-format",
        "text",
        prompt,
    ]
    env = os.environ.copy()
    code, out, timed_out = run_agent_cmd(cmd, timeout, str(ROOT), env)
    pdf = ROOT / "applications" / slug / "resume.pdf"
    answers = ROOT / "applications" / slug / "application_questions.md"
    auth_fail = (
        "not logged in" in out.lower()
        or "not authenticated" in out.lower()
        or "authentication required" in out.lower()
        or "unauthorized" in out.lower()
    )
    if auth_fail:
        return False, (
            "Cursor Agent CLI is not logged in. In a terminal run: agent login"
            "  (or set CURSOR_API_KEY from https://cursor.com/dashboard/api)"
        )
    tail = out[-2000:]
    if timed_out:
        if do_resume and pdf.exists():
            ok_fmt, fmt = format_check_resume(slug)
            if not ok_fmt:
                return False, fmt or tail or "format check failed"
            return True, tail or f"timed out after {timeout}s but PDF exists"
        if do_answers and not do_resume:
            if answers.exists() and len(answers.read_text(encoding="utf-8", errors="replace")) > 80:
                return True, tail or f"timed out after {timeout}s but answers exist"
        return False, tail or f"cursor agent timed out after {timeout}s"
    if do_resume:
        if pdf.exists():
            ok_fmt, fmt = format_check_resume(slug)
            if not ok_fmt:
                return False, fmt or "format check failed"
            return True, tail
        return False, tail or f"cursor agent exit {code} (no PDF)"
    if answers.exists() and len(answers.read_text(encoding="utf-8", errors="replace")) > 80:
        return True, tail
    return False, tail or f"cursor agent exit {code}"


def notify(title: str, body: str) -> None:
    safe_title = title.replace('"', "'")
    safe_body = body.replace('"', "'")[:180]
    script = f'display notification "{safe_body}" with title "{safe_title}" subtitle "Summer 2027 internships"'
    subprocess.run(["osascript", "-e", script], check=False)


def acquire_lock() -> Any:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    fh = LOCK_PATH.open("w")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        raise SystemExit("another daily_run is already in progress")
    fh.write(str(os.getpid()))
    fh.flush()
    return fh


def main() -> int:
    parser = argparse.ArgumentParser(description="Watch SimplifyJobs listings and tailor resumes")
    parser.add_argument("--dry-run", action="store_true", help="fetch and diff only; do not scrape or tailor")
    parser.add_argument("--seed-only", action="store_true", help="mark all current matches seen; do not tailor")
    parser.add_argument("--max", type=int, default=None, help="override max_per_day")
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="rebuild today's HTML/Markdown report from seen.json without scraping",
    )
    parser.add_argument("--cleanup", action="store_true", help="prune old applications/logs/reports and exit")
    parser.add_argument("--dashboard", action="store_true", help="open the local internship dashboard")
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="with --dashboard: no browser, reclaim the port, stay running (launchd)",
    )
    args = parser.parse_args()

    if args.report_only:
        return rebuild_report()
    if args.cleanup:
        run_cleanup(load_config(), log=log)
        return 0
    if args.dashboard:
        from dashboard import main as dash_main

        return dash_main(daemon=args.daemon)

    lock = acquire_lock()
    try:
        return run(args)
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def rebuild_report() -> int:
    cfg = load_config()
    seen = load_json(SEEN_PATH, {})
    leftover = load_json(QUEUE_PATH, [])
    results = collect_today(seen)
    if not results:
        log("no applications from today in seen.json")
    report = write_daily_report(cfg, results, leftover, dry_run=False, log=log)
    return 0


def run(args: argparse.Namespace) -> int:
    cfg = load_config()
    max_n = args.max if args.max is not None else int(cfg.get("max_per_day") or 10)
    listings = fetch_listings(cfg["listings_url"])
    matched = [x for x in listings if matches(x, cfg)]
    matched.sort(key=lambda x: int(x.get("date_posted") or 0), reverse=True)
    log(f"fetched {len(listings)} listings, {len(matched)} match filters")

    seen: dict[str, Any] = load_json(SEEN_PATH, {})
    first_run = not bool(seen)

    if first_run:
        cutoff = datetime.now(timezone.utc).timestamp() - 86400
        seeded = 0
        for item in matched:
            lid = str(item["id"])
            posted = float(item.get("date_posted") or 0)
            if posted < cutoff:
                seen[lid] = {
                    "status": "seeded",
                    "company": item.get("company_name"),
                    "title": item.get("title"),
                    "at": datetime.now().isoformat(timespec="seconds"),
                }
                seeded += 1
        save_json(SEEN_PATH, seen)
        log(f"first run: seeded {seeded} existing listings; will process last 24h only")

    if args.seed_only:
        for item in matched:
            lid = str(item["id"])
            if lid not in seen:
                seen[lid] = {
                    "status": "seeded",
                    "company": item.get("company_name"),
                    "title": item.get("title"),
                    "at": datetime.now().isoformat(timespec="seconds"),
                }
        save_json(SEEN_PATH, seen)
        log(f"seed-only complete, seen={len(seen)}")
        return 0

    queue = [
        x
        for x in matched
        if str(x["id"]) not in seen or seen[str(x["id"])].get("status") in RETRY_STATUSES
    ]
    overflow = 0
    if len(queue) > int(cfg.get("max_queue") or 40):
        overflow = len(queue) - int(cfg["max_queue"])
        dropped = queue[int(cfg["max_queue"]) :]
        for item in dropped:
            seen[str(item["id"])] = {
                "status": "skipped_overflow",
                "company": item.get("company_name"),
                "title": item.get("title"),
                "at": datetime.now().isoformat(timespec="seconds"),
            }
        queue = queue[: int(cfg["max_queue"])]
        save_json(SEEN_PATH, seen)

    dup_idx = index_from_seen(seen, ROOT / "applications")
    kept_queue: list[dict[str, Any]] = []
    dup_rows: list[dict[str, Any]] = []
    for item in queue:
        company = str(item.get("company_name") or "company")
        title = str(item.get("title") or "intern")
        url = str(item.get("url") or "")
        hit = dup_idx.match(company, title, url)
        if hit:
            rec = {
                "id": str(item["id"]),
                "company": company,
                "title": title,
                "url": url,
                "slug": hit,
                "status": "skipped_duplicate",
                "detail": f"duplicate of {hit}",
                "at": datetime.now().isoformat(timespec="seconds"),
            }
            seen[str(item["id"])] = rec
            dup_rows.append(rec)
            log(f"skip duplicate {company} — {title} (same as {hit})")
            continue
        dup_idx.claim(
            company,
            title,
            url,
            re.sub(r"[^a-z0-9]+", "-", f"{company}-{title}".lower()).strip("-")[:72]
            or str(item.get("id") or company),
        )
        kept_queue.append(item)
    queue = kept_queue
    if dup_rows:
        save_json(SEEN_PATH, seen)

    log(f"new unmatched: {len(queue)} (overflow dropped {overflow}; {len(dup_rows)} duplicates)")
    leftover: list[dict[str, Any]] = []
    save_json(QUEUE_PATH, [])

    results: list[dict[str, Any]] = list(dup_rows)
    min_score = float(cfg.get("fit_min_score") or 0.40)
    if args.dry_run:
        slots = 0
        for item in queue:
            if slots >= max_n:
                leftover.append(item)
                continue
            fit = evaluate_listing(item, jd="", min_score=min_score)
            rec = {
                "id": item["id"],
                "company": item.get("company_name"),
                "title": item.get("title"),
                "url": item.get("url"),
                "status": "dry_run" if fit.ok else "skipped_fit",
                "fit": fit.score,
                "detail": fit.reason,
            }
            results.append(rec)
            if fit.ok:
                slots += 1
            else:
                log(f"skip {item.get('company_name')} — {item.get('title')} ({fit.reason[:100]})")
        save_json(
            QUEUE_PATH,
            [
                {
                    "id": x["id"],
                    "company_name": x.get("company_name"),
                    "title": x.get("title"),
                    "url": x.get("url"),
                }
                for x in leftover
            ],
        )
        write_report(cfg, results, leftover, dry_run=True)
        log("dry-run complete")
        return 0

    timeout = int(cfg.get("agent_timeout_s") or cfg.get("claude_timeout_s") or 600)
    do_tailor = bool(cfg.get("tailor", True))
    if do_tailor and queue:
        argv = cursor_agent_argv()
        if not argv:
            log("Cursor Agent CLI not found; install with: curl https://cursor.com/install -fsS | bash")
            return 1
        st = subprocess.run([*argv, "status"], capture_output=True, text=True, timeout=60)
        st_out = ((st.stdout or "") + "\n" + (st.stderr or "")).lower()
        if "not logged in" in st_out or "not authenticated" in st_out:
            log("Cursor Agent CLI is not logged in. Run: agent login")
            return 1

    leftover = []
    slots = 0
    pending = list(queue)
    while pending:
        item = pending.pop(0)
        if slots >= max_n:
            leftover = [item] + pending
            break
        lid = str(item["id"])
        company = str(item.get("company_name") or "company")
        title = str(item.get("title") or "intern")
        url = str(item.get("url") or "")
        prev = seen.get(lid) if isinstance(seen.get(lid), dict) else {}
        slug = str(prev.get("slug") or "") or slugify(company, title, lid)
        status = "scrape_failed"
        detail = ""
        fit_score = None
        try:
            pre = evaluate_listing(item, jd="", min_score=min_score)
            if not pre.ok and pre.score < 0.25:
                log(f"skip {company} — {title} ({pre.reason[:120]})")
                status = "skipped_fit"
                detail = pre.reason
                fit_score = pre.score
                slug = str(prev.get("slug") or "")
            else:
                log(f"scrape {company} — {title}")
                try:
                    scraped = scrape_one(url, browser=True)
                    if scraped.get("apply_clicked"):
                        log(f"clicked apply CTA: {scraped['apply_clicked']}")
                    elif not questions_look_real(scraped.get("questions")):
                        log(f"no apply-form questions yet for {company}")
                except Exception as e:
                    log(f"scrape exception {company}: {type(e).__name__}: {e}")
                    scraped = {"ok": False, "error": f"{type(e).__name__}: {e}", "jd_text": "", "questions": []}
                scraped["company"] = company
                scraped["role"] = title
                jd_text = (scraped.get("jd_text") or "").strip()
                jd_len = len(jd_text)
                job_md = ROOT / "applications" / slug / "job.md"
                fit = evaluate_listing(item, jd=jd_text, min_score=min_score)
                fit_score = fit.score
                if not fit.ok:
                    status = "skipped_fit"
                    detail = fit.reason
                    log(f"skip {company} — {title} ({fit.reason[:120]})")
                    slug = str(prev.get("slug") or "")
                else:
                    if jd_len >= MIN_JD_CHARS or not job_md.exists():
                        write_job_md(slug, item, scraped, copy_master=True)
                    status = "scraped"
                    detail = scraped.get("error") or fit.reason
                    if do_tailor:
                        if not (ROOT / "applications" / slug / "job.md").exists():
                            status = "scrape_failed"
                            detail = detail or "no job.md after scrape"
                            log(f"{status} applications/{slug}/ ({detail[:120]})")
                            slots += 1
                        elif jd_len < MIN_JD_CHARS and not _job_md_has_body(job_md):
                            status = "scrape_failed"
                            detail = detail or f"jd too short ({jd_len} chars)"
                            log(f"{status} applications/{slug}/ ({detail[:120]})")
                            slots += 1
                        else:
                            try:
                                ok, detail = tailor_with_cursor(slug, item, timeout)
                            except Exception as e:
                                ok, detail = False, f"{type(e).__name__}: {e}"
                            status = "tailored" if ok else "tailor_failed"
                            log(f"{status} applications/{slug}/ ({str(detail)[:120]})")
                            tidy_folder(ROOT / "applications" / slug)
                            slots += 1
                    else:
                        log(f"scraped applications/{slug}/")
                        slots += 1
        except Exception as e:
            status = "scrape_failed"
            detail = f"{type(e).__name__}: {e}"
            log(f"{status} applications/{slug}/ ({detail[:120]})")
            slots += 1
        rec = {
            "id": lid,
            "company": company,
            "title": title,
            "url": url,
            "slug": slug,
            "status": status,
            "fit": fit_score,
            "detail": str(detail)[:400],
            "at": datetime.now().isoformat(timespec="seconds"),
        }
        seen[lid] = rec
        save_json(SEEN_PATH, seen)
        results.append({**rec, "detail": str(detail)[:500]})

    save_json(
        QUEUE_PATH,
        [
            {
                "id": x["id"],
                "company_name": x.get("company_name"),
                "title": x.get("title"),
                "url": x.get("url"),
            }
            for x in leftover
        ],
    )

    report = write_report(cfg, collect_today(seen), leftover, dry_run=False)
    run_cleanup(cfg, log=log)
    tailored = sum(1 for r in results if r["status"] == "tailored")
    skipped = sum(1 for r in results if r["status"] in {"skipped_fit", "skipped_duplicate"})
    failed = sum(
        1 for r in results if r["status"] not in {"tailored", "skipped_fit", "skipped_duplicate"}
    )
    summary = (
        f"{tailored} tailored, {skipped} skipped (fit/duplicate), {failed} failed, {len(leftover)} queued"
    )
    log(summary)
    if cfg.get("notify") and (results or cfg.get("notify_if_empty")):
        if results:
            notify("Resume internships", summary)
        elif cfg.get("notify_if_empty"):
            notify("Resume internships", "No new matching internships")
    return 0


def write_report(
    cfg: dict[str, Any],
    results: list[dict[str, Any]],
    leftover: list[dict[str, Any]],
    dry_run: bool,
) -> Path:
    return write_daily_report(cfg, results, leftover, dry_run, log=log)


if __name__ == "__main__":
    raise SystemExit(main())
