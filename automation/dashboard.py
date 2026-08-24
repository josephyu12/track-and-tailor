#!/usr/bin/env python3
"""Local dashboard: past days, apply packs, and custom job analysis.

Bind 127.0.0.1 only. Interactive: make internships-dashboard
Always-on: make internships-install (launchd KeepAlive on login).
"""

from __future__ import annotations

import html
import json
import errno
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

AUTO = Path(__file__).resolve().parent
ROOT = AUTO.parent
APPS = ROOT / "applications"
STATE = AUTO / "state"
SCRAPE = ROOT / ".cursor" / "skills" / "tailor-resume" / "scripts"

sys.path.insert(0, str(AUTO))
sys.path.insert(0, str(SCRAPE))

from cleanup import KEEP_NAME, tidy_folder  # noqa: E402
from daily_run import SEEN_PATH, load_config, load_json, save_json, slugify, tailor_with_cursor, write_job_md  # noqa: E402
from dedupe import (  # noqa: E402
    collapse_rows,
    index_from_applications,
    parse_job_identity,
    remember_deleted,
    same_job,
)
from fit import DEFAULT_MIN_SCORE, evaluate_fit  # noqa: E402
from report import parse_answers_md  # noqa: E402
from scrape_jd import scrape_one  # noqa: E402

TAILOR_STATUS = STATE / "tailor_status.json"
APPLIED_PATH = STATE / "applied.json"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,90}$")
_STATUS_LOCK = threading.Lock()
_APPLIED_LOCK = threading.Lock()
STALE_RUNNING_GRACE_S = 90
ANSWER_NEWER_THAN_START_S = 3

CSS = """
:root { --ink:#1a2332; --muted:#5c6b7a; --line:#e2e8f0; --bg:#f4f6f8; --card:#fff;
  --accent:#0b57d0; --good:#0f7b3c; --warn:#9a6700; --bad:#b3261e; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
  font: 15px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }
a { color: var(--accent); }
.top { background:var(--ink); color:#fff; padding:16px 22px; display:flex; gap:18px;
  align-items:baseline; flex-wrap:wrap; }
.top h1 { margin:0; font-size:18px; font-weight:650; }
.top a { color:#9dc1ff; text-decoration:none; font-size:13px; }
.wrap { display:grid; grid-template-columns: 200px 1fr; max-width:1100px; margin:0 auto; }
.side { padding:18px 12px 48px 18px; }
.side a { display:block; padding:6px 8px; border-radius:8px; text-decoration:none; color:var(--ink); }
.side a:hover, .side a.on { background:#e8eef6; }
.main { padding:18px 20px 64px 8px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; margin:0 0 14px; }
.card h2 { margin:0 0 10px; font-size:16px; }
label { display:block; font-size:12px; font-weight:650; color:var(--muted); margin:8px 0 4px; }
label.checks { font-size:14px; font-weight:500; color:var(--ink); display:flex; gap:8px; align-items:center; }
input[type=text], textarea { width:100%; border:1px solid var(--line); border-radius:8px;
  padding:8px 10px; font: inherit; }
textarea { min-height:120px; font-family: ui-monospace, Menlo, Consolas, monospace; font-size:13px; }
.row2 { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
.actions { display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }
.btn { border:0; border-radius:8px; padding:8px 12px; font-weight:650; font-size:13px;
  cursor:pointer; text-decoration:none; display:inline-flex; }
.btn-apply { background:var(--accent); color:#fff; }
.btn-pdf { background:var(--good); color:#fff; }
.btn-ghost { background:#eef2f6; color:var(--ink); }
.btn-warn { background:#fff4d6; color:#5c4300; }
.btn-danger { background:#fce8e6; color:var(--bad); }
table { width:100%; border-collapse:collapse; font-size:14px; }
th { text-align:left; font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; }
td, th { padding:8px 6px; border-bottom:1px solid var(--line); vertical-align:top; }
.badge { font-size:11px; font-weight:700; border-radius:999px; padding:2px 7px; }
.ok { background:#e8f6ee; color:var(--good); }
.no { background:#fff4d6; color:var(--warn); }
.bad { background:#fce8e6; color:var(--bad); }
.muted { color:var(--muted); font-size:13px; }
pre.answer { white-space:pre-wrap; background:var(--bg); padding:8px 10px; border-radius:8px;
  font: 13px/1.4 ui-monospace, Menlo, Consolas, monospace; margin:0; }
.qa { display:grid; grid-template-columns:1fr auto; gap:8px; align-items:start;
  padding:10px 0; border-bottom:1px solid var(--line); }
.copy { background:var(--ink); color:#fff; border:0; border-radius:8px; padding:7px 10px;
  font-size:12px; font-weight:700; cursor:pointer; }
.banner { background:#e8eef6; border-radius:8px; padding:8px 10px; margin:0 0 12px; }
.did { background:#e8f6ee; color:var(--good); }
tr.applied td { background:#f3faf6; }
.applied-box { display:flex; align-items:center; gap:6px; font-size:13px; font-weight:650; white-space:nowrap; }
.applied-box input { width:16px; height:16px; }
@media (max-width: 800px) { .wrap { grid-template-columns: 1fr; } .row2 { grid-template-columns:1fr; } }
"""


def _cfg() -> dict[str, Any]:
    return load_config()


def _parse_status_at(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        return None


def _load_status_unlocked() -> dict[str, Any]:
    if not TAILOR_STATUS.exists():
        return {}
    try:
        data = json.loads(TAILOR_STATUS.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _write_status_unlocked(data: dict[str, Any]) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    save_json(TAILOR_STATUS, data)


def _artifact_finished(slug: str, started: datetime | None, want: str) -> bool:
    """True when tailor output is newer than the running stamp (not the scrape copy)."""
    started_ts = started.timestamp() if started else 0.0
    pdf = APPS / slug / "resume.pdf"
    answers = APPS / slug / "application_questions.md"
    if "resume" in want and pdf.is_file() and pdf.stat().st_mtime >= started_ts - 1:
        return True
    if want == "answers" and answers.is_file():
        return answers.stat().st_mtime >= started_ts + ANSWER_NEWER_THAN_START_S
    return False


def _reconcile_unlocked(data: dict[str, Any]) -> bool:
    timeout = int((_cfg() or {}).get("agent_timeout_s") or 600) + STALE_RUNNING_GRACE_S
    now = time.time()
    me = os.getpid()
    changed = False
    for slug, rec in data.items():
        if not isinstance(rec, dict) or rec.get("state") != "running":
            continue
        started = _parse_status_at(rec.get("at"))
        started_ts = started.timestamp() if started else 0.0
        want = str(rec.get("detail") or "resume+answers")
        if _artifact_finished(slug, started, want):
            rec["state"] = "done"
            rec["detail"] = (rec.get("detail") or "finished")[:500]
            rec["at"] = datetime.now().isoformat(timespec="seconds")
            rec.pop("pid", None)
            changed = True
            continue
        age = now - started_ts if started_ts else timeout + 1
        dead_worker = rec.get("pid") not in (None, me)
        if dead_worker or age > timeout:
            rec["state"] = "error"
            rec["detail"] = (
                "interrupted (dashboard restarted)" if dead_worker
                else "timed out or status was lost before the job finished"
            )
            rec["at"] = datetime.now().isoformat(timespec="seconds")
            rec.pop("pid", None)
            changed = True
    return changed


def _status() -> dict[str, Any]:
    with _STATUS_LOCK:
        data = _load_status_unlocked()
        if _reconcile_unlocked(data):
            _write_status_unlocked(data)
        return data


def _set_status(slug: str, state: str, detail: str = "") -> None:
    rec: dict[str, Any] = {
        "state": state,
        "detail": detail[:500],
        "at": datetime.now().isoformat(timespec="seconds"),
    }
    if state == "running":
        rec["pid"] = os.getpid()
    with _STATUS_LOCK:
        data = _load_status_unlocked()
        data[slug] = rec
        _write_status_unlocked(data)


def _clear_status(slug: str) -> None:
    with _STATUS_LOCK:
        data = _load_status_unlocked()
        if slug in data:
            data.pop(slug, None)
            _write_status_unlocked(data)


def _load_applied_unlocked() -> dict[str, Any]:
    if not APPLIED_PATH.exists():
        return {}
    try:
        data = json.loads(APPLIED_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _write_applied_unlocked(data: dict[str, Any]) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    save_json(APPLIED_PATH, data)


def _applied() -> dict[str, Any]:
    with _APPLIED_LOCK:
        return _load_applied_unlocked()


def is_applied(slug: str) -> bool:
    rec = _applied().get(slug)
    return bool(isinstance(rec, dict) and rec.get("applied"))


def _related_slugs(slug: str) -> list[str]:
    """Same company+role (or same URL) should share the Applied checkbox."""
    found = [slug]
    ident = parse_job_identity(APPS / slug / "job.md")
    if not ident or not APPS.is_dir():
        return found
    for folder in APPS.iterdir():
        if not folder.is_dir() or folder.name.startswith(".") or folder.name == slug:
            continue
        other = parse_job_identity(folder / "job.md")
        if other and same_job(
            ident["company"],
            ident["title"],
            ident.get("url") or "",
            other["company"],
            other["title"],
            other.get("url") or "",
        ):
            found.append(folder.name)
    return found


def set_applied(slug: str, on: bool, via: str = "toggle") -> None:
    slugs = _related_slugs(slug)
    now = datetime.now().isoformat(timespec="seconds")
    with _APPLIED_LOCK:
        data = _load_applied_unlocked()
        if on:
            for name in slugs:
                data[name] = {"applied": True, "at": now, "via": via}
        else:
            for name in slugs:
                data.pop(name, None)
        _write_applied_unlocked(data)


def delete_form(slug: str, company: str, title: str) -> str:
    qslug = urllib.parse.quote(slug)
    msg = json.dumps(f"Delete {company} — {title}? This removes the application folder.")
    return (
        f'<form method="post" action="/delete/{qslug}" style="display:inline" '
        f'onsubmit="return confirm({msg})">'
        f'<button class="btn btn-danger" type="submit">Delete</button></form>'
    )


def delete_application(slug: str) -> str | None:
    if not SLUG_RE.match(slug):
        return "Bad slug."
    folder = (APPS / slug).resolve()
    if APPS.resolve() not in folder.parents or not folder.is_dir():
        return "Application not found."
    rec = parse_job_folder(folder) or {}
    remember_deleted(
        slug,
        str(rec.get("company") or slug),
        str(rec.get("title") or ""),
        str(rec.get("url") or rec.get("source") or ""),
    )
    shutil.rmtree(folder)
    with _APPLIED_LOCK:
        applied = _load_applied_unlocked()
        if slug in applied:
            applied.pop(slug, None)
            _write_applied_unlocked(applied)
    _clear_status(slug)
    seen = load_json(SEEN_PATH, {})
    changed = False
    for rec in seen.values():
        if isinstance(rec, dict) and rec.get("slug") == slug:
            rec["status"] = "deleted"
            rec["at"] = datetime.now().isoformat(timespec="seconds")
            changed = True
    if changed:
        save_json(SEEN_PATH, seen)
    return None


def apply_link(slug: str, url: str, applied: bool) -> str:
    qslug = urllib.parse.quote(slug)
    checked = " checked" if applied else ""
    box = (
        f'<label class="applied-box"><input type="checkbox" class="js-applied" '
        f'data-slug="{html.escape(slug)}"{checked}> Applied</label>'
    )
    if url:
        btn = (
            f'<a class="btn btn-apply js-apply" href="/go/{qslug}" target="_blank" '
            f'rel="noopener" data-slug="{html.escape(slug)}">Apply</a>'
        )
    else:
        btn = ""
    return f"{btn} {box}"


def parse_job_folder(folder: Path) -> dict[str, Any] | None:
    job = folder / "job.md"
    if not job.exists():
        return None
    text = job.read_text(encoding="utf-8", errors="replace")
    company, role = folder.name, ""
    meta: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            if " — " in title:
                company, role = title.split(" — ", 1)
            else:
                company = title
        elif line.startswith("- ") and ":" in line:
            k, v = line[2:].split(":", 1)
            meta[k.strip().lower()] = v.strip()
    day = meta.get("date") or datetime.fromtimestamp(job.stat().st_mtime).date().isoformat()
    pdf = folder / "resume.pdf"
    fit_path = folder / "fit.json"
    fit = {}
    if fit_path.exists():
        try:
            fit = json.loads(fit_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            fit = {}
    src = meta.get("source") or ""
    return {
        "slug": folder.name,
        "company": company,
        "title": role,
        "date": day,
        "url": src if src.startswith("http") else "",
        "source": src,
        "location": meta.get("location") or "",
        "pdf": pdf.exists(),
        "keep": (folder / KEEP_NAME).exists(),
        "applied": is_applied(folder.name),
        "fit": fit,
        "needs": sum(1 for q in parse_answers_md(folder / "application_questions.md") if q["state"] == "needs"),
    }


def catalog() -> list[dict[str, Any]]:
    if not APPS.is_dir():
        return []
    rows = []
    for folder in APPS.iterdir():
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        rec = parse_job_folder(folder)
        if rec:
            rows.append(rec)
    rows.sort(key=lambda r: (r["date"], r["company"]), reverse=True)
    return collapse_rows(rows)


def days_from(rows: list[dict[str, Any]]) -> list[str]:
    seen = []
    for r in rows:
        if r["date"] not in seen:
            seen.append(r["date"])
    return seen


def page(title: str, body: str, day: str | None = None) -> bytes:
    rows = catalog()
    days = days_from(rows)
    nav = ['<a href="/" class="%s">All days</a>' % ("on" if not day else "")]
    for d in days:
        nav.append(f'<a href="/day/{d}" class="{"on" if day == d else ""}">{html.escape(d)}</a>')
    doc = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title><style>{CSS}</style></head><body>
<header class="top"><h1>Internship dashboard</h1>
<a href="/">Overview</a><a href="/#add">Add a job</a></header>
<div class="wrap"><nav class="side">{"".join(nav) or '<span class="muted">No days yet</span>'}</nav>
<main class="main">{body}</main></div>
<script>
document.querySelectorAll("[data-copy]").forEach(function(btn){{
  btn.addEventListener("click", async function(){{
    const n = document.getElementById(btn.getAttribute("data-copy"));
    const t = n ? n.innerText : "";
    try {{ await navigator.clipboard.writeText(t); }} catch(e) {{
      const ta=document.createElement("textarea"); ta.value=t; document.body.appendChild(ta); ta.select();
      document.execCommand("copy"); ta.remove();
    }}
    const p=btn.textContent; btn.textContent="Copied"; setTimeout(()=>btn.textContent=p, 1100);
  }});
}});
function markAppliedUI(slug, on) {{
  document.querySelectorAll('.js-applied[data-slug="'+slug+'"]').forEach(function(cb){{ cb.checked = on; }});
  document.querySelectorAll('tr[data-slug="'+slug+'"]').forEach(function(tr){{
    tr.classList.toggle("applied", on);
  }});
}}
document.querySelectorAll(".js-apply").forEach(function(a){{
  a.addEventListener("click", function(){{ markAppliedUI(a.getAttribute("data-slug"), true); }});
}});
document.querySelectorAll(".js-applied").forEach(function(cb){{
  cb.addEventListener("change", async function(){{
    const slug = cb.getAttribute("data-slug");
    const on = cb.checked;
    markAppliedUI(slug, on);
    await fetch("/applied/"+encodeURIComponent(slug), {{
      method: "POST",
      headers: {{"Content-Type": "application/x-www-form-urlencoded"}},
      body: "applied=" + (on ? "1" : "0")
    }});
  }});
}});
(function(){{
  const el = document.querySelector(".js-generating");
  if (!el) return;
  const slug = el.getAttribute("data-slug");
  const tick = async function(){{
    try {{
      const r = await fetch("/api/status/"+encodeURIComponent(slug), {{cache:"no-store"}});
      const j = await r.json();
      if (j.state && j.state !== "running") location.reload();
    }} catch (e) {{}}
  }};
  setInterval(tick, 2500);
  setTimeout(tick, 800);
}})();
</script></body></html>"""
    return doc.encode("utf-8")


def add_form(msg: str = "") -> str:
    banner = f'<div class="banner">{html.escape(msg)}</div>' if msg else ""
    return f"""
{banner}
<div class="card" id="add">
  <h2>Analyze a custom job</h2>
  <p class="muted">Paste a posting URL and/or the JD. Analyze scores fit. Check what to generate (rerunnable later on the job page).</p>
  <form method="post" action="/analyze">
    <div class="row2">
      <div><label>Company</label><input type="text" name="company" placeholder="Acme"></div>
      <div><label>Role</label><input type="text" name="role" placeholder="Software Engineer Intern"></div>
    </div>
    <label>Job URL</label>
    <input type="text" name="url" placeholder="https://boards.greenhouse.io/...">
    <label>Or paste the job description</label>
    <textarea name="jd" placeholder="Paste the JD here if the URL is login-walled"></textarea>
    <label class="checks"><input type="checkbox" name="do_resume" value="1" checked> Tailor one-page resume</label>
    <label class="checks"><input type="checkbox" name="do_answers" value="1" checked> Draft application-form answers</label>
    <div class="actions">
      <button class="btn btn-ghost" type="submit" name="mode" value="analyze">Analyze fit only</button>
      <button class="btn btn-apply" type="submit" name="mode" value="run">Analyze + run checked</button>
    </div>
  </form>
</div>
"""


def jobs_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<p class="muted">Nothing here.</p>'
    tr = []
    for r in rows:
        slug = r["slug"]
        apply = r["url"]
        pdf = f'<a class="btn btn-pdf" href="/file/{urllib.parse.quote(slug)}/resume.pdf">PDF</a>' if r["pdf"] else '<span class="muted">—</span>'
        applied = bool(r.get("applied"))
        apply_b = apply_link(slug, apply, applied)
        cls = ' class="applied"' if applied else ""
        mark = ' <span class="badge did">applied</span>' if applied else ""
        fit = r.get("fit") or {}
        score = fit.get("score")
        ok = fit.get("ok")
        if score is None:
            badge = ""
        elif ok:
            badge = f'<span class="badge ok">{score:.2f}</span>'
        else:
            badge = f'<span class="badge no">{score:.2f}</span>'
        pin = " · pinned" if r.get("keep") else ""
        needs = f' · {r["needs"]} need you' if r.get("needs") else ""
        dups = int(r.get("dup_count") or 0)
        if dups:
            loc_bit = ""
            extra_locs = [x for x in (r.get("dup_locations") or []) if x]
            if extra_locs:
                loc_bit = " · " + "; ".join(html.escape(x) for x in extra_locs[:3])
            needs += f' · {dups} similar listing{"s" if dups != 1 else ""}{loc_bit}'
        tr.append(
            f'<tr{cls} data-slug="{html.escape(slug)}"><td>{html.escape(r["date"])}</td>'
            f'<td><a href="/app/{urllib.parse.quote(slug)}"><strong>{html.escape(r["company"])}</strong><br>'
            f'<span class="muted">{html.escape(r["title"])}{pin}{needs}</span></a>{mark}</td>'
            f'<td>{badge}</td><td>{apply_b} {pdf} {delete_form(slug, r["company"], r["title"])}</td></tr>'
        )
    return (
        "<table><thead><tr><th>Date</th><th>Role</th><th>Fit</th><th>Apply</th></tr></thead><tbody>"
        + "".join(tr)
        + "</tbody></table>"
    )


def overview_body(msg: str = "") -> str:
    rows = catalog()
    today = date.today().isoformat()
    today_rows = [r for r in rows if r["date"] == today]
    pdfs = sum(1 for r in rows if r["pdf"])
    applied_n = sum(1 for r in rows if r.get("applied"))
    return (
        add_form(msg)
        + f'<div class="card"><h2>Today — {html.escape(today)}</h2>'
        + f'<p class="muted">{len(today_rows)} jobs today · {len(rows)} kept on disk · {pdfs} PDFs · {applied_n} applied</p>'
        + jobs_table(today_rows)
        + "</div>"
        + '<div class="card"><h2>All saved applications</h2>'
        + jobs_table(rows)
        + "</div>"
    )


def day_body(day: str) -> str:
    rows = [r for r in catalog() if r["date"] == day]
    return f'<div class="card"><h2>{html.escape(day)}</h2>{jobs_table(rows)}</div>' + add_form()


def app_body(slug: str) -> str:
    folder = APPS / slug
    rec = parse_job_folder(folder)
    if not rec:
        return '<p class="muted">Not found.</p>'
    fit = rec.get("fit") or {}
    st = _status().get(slug) or {}
    banner = ""
    if st.get("state") == "running":
        banner = (
            f'<div class="banner js-generating" data-slug="{html.escape(slug)}">'
            "Generating in progress… this page updates when it finishes.</div>"
        )
    elif st.get("state") == "done":
        banner = '<div class="banner">Done. Resume and/or answers were rewritten from master.</div>'
    elif st.get("state") == "error":
        banner = f'<div class="banner">Failed: {html.escape(str(st.get("detail") or ""))}</div>'
    score = fit.get("score")
    fit_line = ""
    if score is not None:
        cls = "ok" if fit.get("ok") else "no"
        fit_line = f'<p><span class="badge {cls}">fit {score:.2f}</span> {html.escape(str(fit.get("reason") or ""))}</p>'
    apply = rec["url"]
    applied = bool(rec.get("applied"))
    btns = [apply_link(slug, apply, applied)]
    if rec["pdf"]:
        btns.append(f'<a class="btn btn-pdf" href="/file/{urllib.parse.quote(slug)}/resume.pdf">Resume PDF</a>')
    btns.append(f'<a class="btn btn-ghost" href="/file/{urllib.parse.quote(slug)}/job.md">job.md</a>')
    if st.get("state") != "running":
        qslug = urllib.parse.quote(slug)
        btns.append(
            f'<form method="post" action="/generate/{qslug}" style="display:inline">'
            f'<input type="hidden" name="do_resume" value="1">'
            f'<button class="btn btn-warn" type="submit">Rerun resume</button></form>'
        )
        btns.append(
            f'<form method="post" action="/generate/{qslug}" style="display:inline">'
            f'<input type="hidden" name="do_answers" value="1">'
            f'<button class="btn btn-warn" type="submit">Rerun answers</button></form>'
        )
        btns.append(
            f'<form method="post" action="/generate/{qslug}" style="display:inline">'
            f'<input type="hidden" name="do_resume" value="1">'
            f'<input type="hidden" name="do_answers" value="1">'
            f'<button class="btn btn-apply" type="submit">Rerun both</button></form>'
        )
    btns.append(delete_form(slug, rec["company"], rec["title"]))
    items = parse_answers_md(folder / "application_questions.md")
    qa = []
    for it in items:
        aid = f"a-{it['n']}"
        qa.append(
            f'<div class="qa"><div><div class="muted">{it["n"]}. {html.escape(it["prompt"])}</div>'
            f'<pre class="answer" id="{aid}">{html.escape(it["answer"])}</pre></div>'
            f'<button class="copy" type="button" data-copy="{aid}">Copy</button></div>'
        )
    loc = html.escape(rec.get("location") or "")
    return f"""
{banner}
<div class="card">
  <h2>{html.escape(rec["company"])} — {html.escape(rec["title"])}</h2>
  <p class="muted">{html.escape(rec["date"])} · {loc} · <code>{html.escape(slug)}</code></p>
  {fit_line}
  <div class="actions">{"".join(btns)}</div>
</div>
<div class="card"><h2>Answers to paste</h2>
{"".join(qa) or '<p class="muted">No form questions captured.</p>'}
</div>
"""


def analyze(fields: dict[str, str]) -> tuple[str, str]:
    url = (fields.get("url") or "").strip()
    jd = (fields.get("jd") or "").strip()
    company = (fields.get("company") or "").strip()
    role = (fields.get("role") or "").strip()
    mode = (fields.get("mode") or "analyze").strip()
    if not url and not jd:
        return "", "Need a URL or a pasted JD."
    if len(jd) > 200_000:
        return "", "JD is too long."
    scraped: dict[str, Any]
    if url:
        if not re.match(r"^https?://", url, re.I):
            return "", "URL must start with http."
        scraped = scrape_one(url, browser=True)
    else:
        scraped = {
            "ok": True,
            "company": company,
            "role": role,
            "location": "",
            "jd_text": jd,
            "questions": [],
            "error": None,
        }
    if company:
        scraped["company"] = company
    if role:
        scraped["role"] = role
    company = str(scraped.get("company") or company or "Company")
    role = str(scraped.get("role") or role or "Intern")
    jd_text = (scraped.get("jd_text") or jd).strip()
    cfg = _cfg()
    min_score = float(cfg.get("fit_min_score") or DEFAULT_MIN_SCORE)
    fit = evaluate_fit(role, jd_text, "custom", min_score=min_score, company=company)
    listing = {
        "id": "custom-" + datetime.now().strftime("%Y%m%d%H%M%S"),
        "company_name": company,
        "title": role,
        "url": url or "pasted",
        "category": "custom",
        "locations": [str(scraped.get("location") or "")],
    }
    existing = index_from_applications(APPS).match(company, role, url)
    if existing:
        slug = existing
    else:
        slug = slugify(company, role, str(listing["id"]))
        write_job_md(slug, listing, scraped, copy_master=True)
        folder = APPS / slug
        (folder / KEEP_NAME).write_text(
            "Custom analysis. Delete this file to allow auto-gc.\n", encoding="utf-8"
        )
    folder = APPS / slug
    (folder / "fit.json").write_text(
        json.dumps({"ok": fit.ok, "score": fit.score, "reason": fit.reason, "custom": True}, indent=2),
        encoding="utf-8",
    )
    if mode in {"run", "tailor"}:
        if mode == "tailor":
            do_resume, do_answers = True, True
        else:
            do_resume = fields.get("do_resume") == "1"
            do_answers = fields.get("do_answers") == "1"
        if do_resume or do_answers:
            start_tailor(slug, listing, do_resume=do_resume, do_answers=do_answers)
    return slug, ""


def start_tailor(
    slug: str,
    listing: dict[str, Any],
    *,
    do_resume: bool = True,
    do_answers: bool = True,
) -> None:
    bits = [n for n, on in (("resume", do_resume), ("answers", do_answers)) if on]
    _set_status(slug, "running", "+".join(bits))
    timeout = int(_cfg().get("agent_timeout_s") or 600)

    def work() -> None:
        try:
            ok, detail = tailor_with_cursor(
                slug, listing, timeout, do_resume=do_resume, do_answers=do_answers
            )
            tidy_folder(APPS / slug)
            _set_status(slug, "done" if ok else "error", detail)
        except Exception as e:
            _set_status(slug, "error", f"{type(e).__name__}: {e}")

    threading.Thread(target=work, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _redir(self, loc: str) -> None:
        self.send_response(303)
        self.send_header("Location", loc)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/":
            msg = urllib.parse.parse_qs(parsed.query).get("msg", [""])[0]
            self._send(200, page("Internship dashboard", overview_body(msg)))
            return
        if path.startswith("/day/"):
            day = path.split("/day/", 1)[-1]
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
                self._send(404, page("Not found", "<p>Bad date.</p>"))
                return
            self._send(200, page(f"Jobs {day}", day_body(day), day=day))
            return
        if path.startswith("/app/"):
            slug = path.split("/app/", 1)[-1]
            if not SLUG_RE.match(slug):
                self._send(404, page("Not found", "<p>Bad slug.</p>"))
                return
            self._send(200, page(slug, app_body(slug)))
            return
        if path.startswith("/go/"):
            slug = urllib.parse.unquote(path.split("/go/", 1)[-1])
            rec = parse_job_folder(APPS / slug) if SLUG_RE.match(slug) else None
            if not rec:
                self._send(404, page("Not found", "<p>Unknown job.</p>"))
                return
            set_applied(slug, True, via="apply-click")
            dest = rec.get("url") or ("/app/" + urllib.parse.quote(slug))
            self._redir(dest)
            return
        if path.startswith("/file/"):
            rest = path.split("/file/", 1)[-1]
            slug, _, name = rest.partition("/")
            if not SLUG_RE.match(slug) or name not in {
                "resume.pdf",
                "job.md",
                "application_questions.md",
                "resume.tex",
            }:
                self._send(404, b"not found", "text/plain")
                return
            target = (APPS / slug / name).resolve()
            if APPS.resolve() not in target.parents or not target.is_file():
                self._send(404, b"not found", "text/plain")
                return
            data = target.read_bytes()
            ctype = {
                ".pdf": "application/pdf",
                ".md": "text/markdown; charset=utf-8",
                ".tex": "text/plain; charset=utf-8",
            }.get(target.suffix, "application/octet-stream")
            self._send(200, data, ctype)
            return
        if path.startswith("/api/status/"):
            slug = path.split("/api/status/", 1)[-1]
            body = json.dumps(_status().get(slug) or {}).encode()
            self._send(200, body, "application/json")
            return
        self._send(404, page("Not found", "<p>Not found.</p>"))

    def do_POST(self) -> None:  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(min(n, 400_000)).decode("utf-8", errors="replace")
        fields = {k: v[0] if v else "" for k, v in urllib.parse.parse_qs(raw, keep_blank_values=True).items()}
        path = urllib.parse.urlparse(self.path).path
        if path == "/analyze":
            slug, err = analyze(fields)
            if err:
                self._send(200, page("Internship dashboard", overview_body(err)))
                return
            self._redir("/app/" + urllib.parse.quote(slug))
            return
        if path.startswith("/tailor/") or path.startswith("/generate/"):
            key = "/generate/" if path.startswith("/generate/") else "/tailor/"
            slug = path.split(key, 1)[-1]
            rec = parse_job_folder(APPS / slug) if SLUG_RE.match(slug) else None
            if not rec:
                self._send(404, page("Not found", "<p>Unknown job.</p>"))
                return
            listing = {
                "company_name": rec["company"],
                "title": rec["title"],
                "url": rec["url"] or "pasted",
            }
            if key == "/tailor/":
                do_resume, do_answers = True, True
            else:
                do_resume = fields.get("do_resume") == "1"
                do_answers = fields.get("do_answers") == "1"
            if not do_resume and not do_answers:
                self._redir("/app/" + urllib.parse.quote(slug))
                return
            start_tailor(slug, listing, do_resume=do_resume, do_answers=do_answers)
            self._redir("/app/" + urllib.parse.quote(slug))
            return
        if path.startswith("/applied/"):
            slug = urllib.parse.unquote(path.split("/applied/", 1)[-1])
            if not SLUG_RE.match(slug) or not parse_job_folder(APPS / slug):
                self._send(404, b"not found", "text/plain")
                return
            on = fields.get("applied", "1") in {"1", "on", "true", "yes"}
            set_applied(slug, on, via="toggle")
            self._send(200, json.dumps({"ok": True, "applied": on}).encode(), "application/json")
            return
        if path.startswith("/delete/"):
            slug = path.split("/delete/", 1)[-1]
            err = delete_application(slug)
            if err:
                self._send(200, page("Internship dashboard", overview_body(err)))
                return
            self._redir("/")
            return
        self._send(404, b"not found", "text/plain")


class DashboardServer(ThreadingHTTPServer):
    allow_reuse_address = True


def _open_browser(url: str) -> None:
    for app in ("Google Chrome", "Safari"):
        try:
            if subprocess.run(["open", "-a", app, url], check=False).returncode == 0:
                return
        except OSError:
            continue
    print("Open that URL in a browser (not RStudio).", flush=True)


def _already_serving(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1.5) as resp:
            return 200 <= resp.status < 400
    except OSError:
        return False


def _pids_on_port(port: int) -> list[int]:
    try:
        out = subprocess.check_output(
            ["lsof", "-nP", f"-tiTCP:{port}", "-sTCP:LISTEN"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    return [int(p) for p in out.split() if p.strip().isdigit()]


def _reclaim_port(port: int) -> None:
    me = os.getpid()
    for sig, pause in ((signal.SIGTERM, 0.5), (signal.SIGKILL, 0.2)):
        pids = [p for p in _pids_on_port(port) if p != me]
        if not pids:
            return
        for pid in pids:
            try:
                os.kill(pid, sig)
            except OSError:
                pass
        time.sleep(pause)


def main(daemon: bool | None = None) -> int:
    if daemon is None:
        daemon = "--daemon" in sys.argv
    cfg = _cfg()
    port = int(cfg.get("dashboard_port") or 8765)
    url = f"http://127.0.0.1:{port}/"
    if not daemon and _already_serving(port):
        print(f"Already running at {url}", flush=True)
        _open_browser(url)
        return 0
    try:
        server = DashboardServer(("127.0.0.1", port), Handler)
    except OSError as e:
        if e.errno != errno.EADDRINUSE:
            print(f"Could not bind {url}: {e}", flush=True)
            return 1
        if not daemon and _already_serving(port):
            print(f"Already running at {url}", flush=True)
            _open_browser(url)
            return 0
        _reclaim_port(port)
        try:
            server = DashboardServer(("127.0.0.1", port), Handler)
        except OSError as e2:
            print(f"Could not bind {url}: {e2}", flush=True)
            return 1
    print(f"Dashboard {url}", flush=True)
    _status()
    if not daemon:
        _open_browser(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
