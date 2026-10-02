#!/usr/bin/env python3
"""Daily internship report: clickable apply links, resumes, copy-paste answers."""

from __future__ import annotations

import html
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = Path(__file__).resolve().parent / "reports"
APPLICATIONS = ROOT / "applications"
SCRAPE = ROOT / ".cursor" / "skills" / "tailor-resume" / "scripts"

sys.path.insert(0, str(SCRAPE))
from check_resume import submit_pdf_path  # noqa: E402

HEADING_RE = re.compile(
    r"^##\s+(\d+)\.\s+(.*?)(?:\s+\((required|optional)(?:,\s*([^)]+))?\))?\s*$"
)
PLAIN_H2_RE = re.compile(r"^##\s+(.+)$")
ANSWER_MARK_RE = re.compile(r"\*\*Answer:\*\*\s*", re.I)


def _rel(target: Path, start: Path) -> str:
    t = target.resolve().parts
    s = start.resolve().parts
    i = 0
    while i < min(len(t), len(s)) and t[i] == s[i]:
        i += 1
    ups = [".."] * (len(s) - i)
    downs = list(t[i:])
    return "/".join(ups + downs) if ups or downs else "."


def _extract_answer(rest: str) -> tuple[str, str]:
    options = ""
    for line in rest.splitlines():
        stripped = line.strip()
        if stripped.startswith("Options:") or stripped.startswith("**Options:**"):
            options = re.sub(r"^\*{0,2}Options:\*{0,2}\s*", "", stripped).strip()
            options = options.replace(" | ", "; ")
            break
    marked = ANSWER_MARK_RE.search(rest)
    if marked:
        body = rest[marked.end() :]
        src = re.search(r"(?m)^\*\*Source:\*\*", body)
        if src:
            body = body[: src.start()]
        return body.strip(), options
    body_lines: list[str] = []
    for line in rest.splitlines():
        stripped = line.strip()
        if stripped.startswith("Options:") or stripped.startswith("**Options:**") or stripped.startswith("**Type:**"):
            continue
        body_lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(body_lines)).strip(), options


def parse_answers_md(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    chunks = re.split(r"\n(?=##\s+)", text)
    items: list[dict[str, Any]] = []
    n = 0
    for chunk in chunks:
        first, _, rest = chunk.strip().partition("\n")
        numbered = HEADING_RE.match(first.strip())
        plain = PLAIN_H2_RE.match(first.strip())
        if not numbered and not plain:
            continue
        n += 1
        if numbered:
            prompt = (numbered.group(2) or "").strip()
            required = (numbered.group(3) or "") == "required"
            kind = (numbered.group(4) or "").strip()
            idx = int(numbered.group(1))
        else:
            prompt = (plain.group(1) or "").strip()
            required = "required" in prompt.lower()
            kind = ""
            idx = n
        answer, options = _extract_answer(rest)
        items.append(
            {
                "n": idx,
                "prompt": prompt,
                "required": required,
                "kind": kind,
                "options": options,
                "answer": answer,
                "state": classify_answer(kind, answer),
            }
        )
    return items


def classify_answer(kind: str, answer: str) -> str:
    if not answer or answer.startswith("_No application"):
        return "empty"
    for line in answer.splitlines():
        lead = line.strip()
        if lead.startswith("**Needs user**") or lead.startswith("Needs user"):
            return "needs"
    lead = answer.lstrip()
    if kind == "upload" or lead.lower().startswith("upload "):
        return "upload"
    if lead.startswith("(optional"):
        return "optional"
    return "ready"


def job_location(slug: str) -> str:
    path = APPLICATIONS / slug / "job.md"
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("- Location:"):
            return line.split(":", 1)[1].strip()
    return ""


def job_paths(slug: str) -> dict[str, Path]:
    folder = APPLICATIONS / slug
    return {
        "folder": folder,
        "pdf": submit_pdf_path(folder),
        "tex": folder / "resume.tex",
        "answers": folder / "application_questions.md",
        "job": folder / "job.md",
    }


def collect_today(seen: dict[str, Any], day: str | None = None) -> list[dict[str, Any]]:
    day = day or date.today().isoformat()
    skip = {"seeded", "skipped_overflow", "dry_run", "deleted"}
    rows: list[dict[str, Any]] = []
    for rec in seen.values():
        if not isinstance(rec, dict):
            continue
        if rec.get("status") in skip:
            continue
        at = str(rec.get("at") or "")
        if not at.startswith(day):
            continue
        if not rec.get("slug"):
            continue
        rows.append(rec)
    rows.sort(key=lambda r: (str(r.get("at") or ""), str(r.get("company") or "")))
    return rows


def write_daily_report(
    cfg: dict[str, Any],
    results: list[dict[str, Any]],
    leftover: list[dict[str, Any]],
    dry_run: bool,
    log=print,
) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    day = date.today().isoformat()
    md_path = REPORTS_DIR / f"{day}.md"
    html_path = REPORTS_DIR / f"{day}.html"
    md_path.write_text(render_markdown(cfg, results, leftover, dry_run, day), encoding="utf-8")
    html_path.write_text(render_html(cfg, results, leftover, dry_run, day), encoding="utf-8")
    if log:
        log(f"wrote {html_path}")
        log(f"wrote {md_path}")
    return html_path


def _counts(results: list[dict[str, Any]]) -> dict[str, int]:
    out = {"tailored": 0, "failed": 0, "needs": 0, "ready_fields": 0, "skipped": 0}
    for r in results:
        st = r.get("status")
        if st == "tailored":
            out["tailored"] += 1
        elif st in {"skipped_fit", "skipped_duplicate", "skipped_term"}:
            out["skipped"] += 1
        elif st not in {"scraped", "dry_run"}:
            out["failed"] += 1
        slug = r.get("slug") or ""
        if not slug or st in {"skipped_fit", "skipped_duplicate", "skipped_term"}:
            continue
        for item in parse_answers_md(job_paths(slug)["answers"]):
            if item["state"] == "needs":
                out["needs"] += 1
            elif item["state"] in {"ready", "upload"}:
                out["ready_fields"] += 1
    return out


def _partition(results: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    skipped = [r for r in results if r.get("status") in {"skipped_fit", "skipped_duplicate", "skipped_term"}]
    rest = [r for r in results if r.get("status") not in {"skipped_fit", "skipped_duplicate", "skipped_term"}]
    return rest, skipped


def render_markdown(
    cfg: dict[str, Any],
    results: list[dict[str, Any]],
    leftover: list[dict[str, Any]],
    dry_run: bool,
    day: str,
) -> str:
    counts = _counts(results)
    apply_rows, skipped = _partition(results)
    lines = [
        f"# Internship applications — {day}",
        "",
        f"Source: {cfg.get('source')}",
        f"Mode: {'dry-run' if dry_run else 'live'}",
        f"Ready: **{counts['tailored']}** tailored · **{counts['skipped']}** skipped (fit / duplicate / term) · **{counts['needs']}** fields need you · {len(leftover)} still queued",
        "",
        "Open the HTML report for one-click Apply / Resume / Copy: "
        f"`automation/reports/{day}.html`",
        "",
        "## Today",
        "",
        "| | Company | Role | Apply | Resume | Answers |",
        "|---:|---|---|---|---|---|",
    ]
    if not apply_rows:
        lines += ["", "_None today._", ""]
    for i, r in enumerate(apply_rows, 1):
        slug = str(r.get("slug") or "")
        paths = job_paths(slug) if slug else {}
        pdf = paths.get("pdf")
        ans = paths.get("answers")
        apply = str(r.get("url") or "")
        apply_md = f"[Apply]({apply})" if apply else "—"
        resume_md = f"[PDF]({_rel(pdf, REPORTS_DIR)})" if pdf and pdf.exists() else "—"
        answers_md = f"[Answers]({_rel(ans, REPORTS_DIR)})" if ans and ans.exists() else "—"
        status = r.get("status") or ""
        lines.append(
            f"| {i} | **{r.get('company') or ''}** · `{status}` | {r.get('title') or ''} | "
            f"{apply_md} | {resume_md} | {answers_md} |"
        )
    lines += ["", "## Answers to paste", ""]
    for r in apply_rows:
        slug = str(r.get("slug") or "")
        if not slug:
            continue
        lines += _markdown_job(r, slug)
    lines += ["## Skipped — not a fit or duplicate", ""]
    if not skipped:
        lines.append("_None._")
    for r in skipped:
        apply = str(r.get("url") or "")
        why = str(r.get("detail") or r.get("reason") or "below fit threshold")
        name = f"{r.get('company')} — {r.get('title')}"
        score = r.get("fit")
        score_s = f" · score {score:.2f}" if isinstance(score, (int, float)) else ""
        if apply:
            lines.append(f"- [{name}]({apply}){score_s}")
        else:
            lines.append(f"- {name}{score_s}")
        lines.append(f"  - {why}")
    lines += ["", "## Still queued", ""]
    if not leftover:
        lines.append("_Empty._")
    for item in leftover:
        url = item.get("url") or ""
        name = f"{item.get('company_name') or item.get('company')} — {item.get('title')}"
        if url:
            lines.append(f"- [{name}]({url})")
        else:
            lines.append(f"- {name}")
    lines.append("")
    return "\n".join(lines)


def _markdown_job(r: dict[str, Any], slug: str) -> list[str]:
    paths = job_paths(slug)
    loc = job_location(slug)
    apply = str(r.get("url") or "")
    links = []
    if apply:
        links.append(f"**[Apply]({apply})**")
    if paths["pdf"].exists():
        links.append(f"**[Resume PDF]({_rel(paths['pdf'], REPORTS_DIR)})**")
        links.append(f"`open \"{paths['pdf']}\"`")
    if paths["answers"].exists():
        links.append(f"[Full answers]({_rel(paths['answers'], REPORTS_DIR)})")
    loc_bit = f" · {loc}" if loc else ""
    lines = [
        f"### {r.get('company')} — {r.get('title')}{loc_bit}",
        "",
        " · ".join(links) if links else f"`applications/{slug}/`",
        "",
    ]
    items = parse_answers_md(paths["answers"])
    if not items:
        lines += ["_No form questions captured. Fill the apply page by hand._", ""]
        return lines
    needs = [it for it in items if it["state"] == "needs"]
    if needs:
        lines.append("**You must fill:** " + "; ".join(it["prompt"] for it in needs))
        lines.append("")
    for it in items:
        flag = ""
        if it["state"] == "needs":
            flag = " — NEEDS YOU"
        elif it["state"] == "upload":
            flag = " — attach PDF"
        req = "required" if it["required"] else "optional"
        lines.append(f"**{it['n']}. {it['prompt']}** ({req}{flag})")
        lines.append("")
        if it["state"] == "upload" and paths["pdf"].exists():
            lines.append(f"Attach [{paths['pdf'].name}]({_rel(paths['pdf'], REPORTS_DIR)})")
            extra = it["answer"]
            if extra and not extra.lower().startswith("upload "):
                lines.append("")
                lines.append("```")
                lines.append(extra)
                lines.append("```")
        else:
            lines.append("```")
            lines.append(it["answer"] or "")
            lines.append("```")
        lines.append("")
    return lines


def render_html(
    cfg: dict[str, Any],
    results: list[dict[str, Any]],
    leftover: list[dict[str, Any]],
    dry_run: bool,
    day: str,
) -> str:
    counts = _counts(results)
    apply_rows, skipped = _partition(results)
    jobs_html = []
    toc = []
    for i, r in enumerate(apply_rows, 1):
        slug = str(r.get("slug") or "")
        anchor = f"job-{i}"
        company = html.escape(str(r.get("company") or ""))
        title = html.escape(str(r.get("title") or ""))
        toc.append(
            f'<a href="#{anchor}"><span class="toc-n">{i}</span>'
            f"<strong>{company}</strong> {title}</a>"
        )
        jobs_html.append(_html_job(r, slug, i, anchor))
    leftover_html = ""
    if leftover:
        items = []
        for item in leftover:
            name = html.escape(
                f"{item.get('company_name') or item.get('company')} — {item.get('title')}"
            )
            url = item.get("url") or ""
            if url:
                items.append(f'<li><a href="{html.escape(url)}">{name}</a></li>')
            else:
                items.append(f"<li>{name}</li>")
        leftover_html = "<ul class='queue'>" + "".join(items) + "</ul>"
    else:
        leftover_html = "<p class='muted'>Nothing queued.</p>"

    skipped_html = "<p class='muted'>None.</p>"
    if skipped:
        items = []
        for r in skipped:
            name = html.escape(f"{r.get('company')} — {r.get('title')}")
            url = str(r.get("url") or "")
            why = html.escape(str(r.get("detail") or "below fit threshold"))
            score = r.get("fit")
            score_s = f" · {score:.2f}" if isinstance(score, (int, float)) else ""
            label = f'<a href="{html.escape(url)}">{name}</a>' if url else name
            items.append(f"<li>{label}{score_s}<div class='muted'>{why}</div></li>")
        skipped_html = "<ul class='queue'>" + "".join(items) + "</ul>"

    jobs_block = "".join(jobs_html) if jobs_html else "<p class='muted'>None today.</p>"
    toc_block = "".join(toc) if toc else "<span class='muted'>No jobs</span>"
    source = html.escape(str(cfg.get("source") or ""))
    mode = "dry-run" if dry_run else "live"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Internship applications — {html.escape(day)}</title>
<style>
  :root {{
    --ink: #1a2332;
    --muted: #5c6b7a;
    --line: #e2e8f0;
    --bg: #f6f7f9;
    --card: #fff;
    --accent: #0b57d0;
    --accent-ink: #fff;
    --good: #0f7b3c;
    --good-bg: #e8f6ee;
    --warn: #9a6700;
    --warn-bg: #fff4d6;
    --bad: #b3261e;
    --bad-bg: #fce8e6;
    --upload: #1f3a5f;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--ink);
    font: 15px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  }}
  header {{
    background: var(--ink);
    color: #fff;
    padding: 28px 24px 22px;
  }}
  header h1 {{ margin: 0 0 6px; font-size: 22px; font-weight: 650; }}
  header p {{ margin: 0; color: #c5d0dc; font-size: 13px; }}
  header a {{ color: #9dc1ff; }}
  .wrap {{ max-width: 920px; margin: 0 auto; padding: 0 20px 64px; }}
  .stats {{
    display: flex; gap: 8px; flex-wrap: wrap; margin: 16px 0 0;
  }}
  .stat {{
    background: #243044; color: #e8eef5; border-radius: 999px;
    padding: 4px 10px; font-size: 12px; font-weight: 600;
  }}
  .toc {{
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 12px;
    padding: 8px;
    margin: 18px 0 22px;
    display: grid;
    gap: 2px;
  }}
  .toc a {{
    display: flex; gap: 10px; align-items: baseline;
    text-decoration: none; color: var(--ink);
    padding: 8px 10px; border-radius: 8px;
  }}
  .toc a:hover {{ background: var(--bg); }}
  .toc-n {{
    color: var(--muted); font-variant-numeric: tabular-nums; min-width: 1.4em;
  }}
  .job {{
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 18px 18px 8px;
    margin: 0 0 18px;
  }}
  .job h2 {{ margin: 0 0 4px; font-size: 18px; }}
  .meta {{ color: var(--muted); font-size: 13px; margin-bottom: 12px; }}
  .actions {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 14px; }}
  .btn {{
    display: inline-flex; align-items: center; gap: 6px;
    padding: 8px 12px; border-radius: 8px; font-weight: 650;
    font-size: 13px; text-decoration: none; border: 0; cursor: pointer;
  }}
  .btn-apply {{ background: var(--accent); color: var(--accent-ink); }}
  .btn-pdf {{ background: var(--good); color: #fff; }}
  .btn-ghost {{ background: #eef2f6; color: var(--ink); }}
  .btn:disabled, .btn.is-missing {{ opacity: .45; pointer-events: none; }}
  .badge {{
    display: inline-block; font-size: 11px; font-weight: 700; letter-spacing: .02em;
    text-transform: uppercase; padding: 2px 7px; border-radius: 999px; margin-left: 8px;
    vertical-align: middle;
  }}
  .badge-tailored {{ background: var(--good-bg); color: var(--good); }}
    .badge-failed {{ background: var(--bad-bg); color: var(--bad); }}
    .badge-skipped {{ background: var(--warn-bg); color: var(--warn); }}
    .badge-other {{ background: #eef2f6; color: var(--muted); }}
  .needs-box {{
    background: var(--warn-bg); color: #5c4300; border-radius: 8px;
    padding: 8px 10px; font-size: 13px; margin: 0 0 12px;
  }}
  .qa {{ border-top: 1px solid var(--line); }}
  .row {{
    display: grid; grid-template-columns: 1fr auto;
    gap: 10px; align-items: start;
    padding: 10px 0;
    border-bottom: 1px solid var(--line);
  }}
  .prompt {{ font-size: 12px; color: var(--muted); font-weight: 650; margin-bottom: 4px; }}
  .prompt .tag {{ font-weight: 600; color: #98a5b3; }}
  .answer {{
    margin: 0; white-space: pre-wrap; word-break: break-word;
    font: 14px/1.4 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    background: var(--bg); padding: 8px 10px; border-radius: 8px;
  }}
  .row.needs .answer {{ background: var(--warn-bg); }}
  .row.upload .answer {{ background: #eef3fa; }}
  .copy {{
    background: var(--ink); color: #fff; border: 0; border-radius: 8px;
    padding: 7px 10px; font-weight: 700; font-size: 12px; cursor: pointer;
    min-width: 64px;
  }}
  .copy.copied {{ background: var(--good); }}
  .copy-all {{ margin: 8px 0 12px; }}
  h3 {{ font-size: 14px; margin: 28px 0 8px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }}
  .queue {{ padding-left: 18px; }}
  .muted {{ color: var(--muted); }}
  .path {{ font-size: 11px; color: var(--muted); margin-top: 4px; word-break: break-all; }}
</style>
</head>
<body>
<header>
  <div class="wrap">
    <h1>Internship applications — {html.escape(day)}</h1>
    <p>{mode} · <a href="{source}">{source}</a></p>
    <div class="stats">
      <span class="stat">{counts['tailored']} tailored</span>
      <span class="stat">{counts['skipped']} skipped</span>
      <span class="stat">{counts['needs']} need you</span>
      <span class="stat">{len(leftover)} queued</span>
    </div>
  </div>
</header>
<div class="wrap">
  <nav class="toc">{toc_block}</nav>
  {jobs_block}
  <h3>Skipped — not a fit or duplicate</h3>
  {skipped_html}
  <h3>Still queued</h3>
  {leftover_html}
</div>
<script>
document.querySelectorAll("[data-copy]").forEach(function (btn) {{
  btn.addEventListener("click", async function () {{
    const id = btn.getAttribute("data-copy");
    const node = document.getElementById(id);
    const text = node ? node.innerText : "";
    try {{
      await navigator.clipboard.writeText(text);
    }} catch (err) {{
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }}
    const prev = btn.textContent;
    btn.textContent = "Copied";
    btn.classList.add("copied");
    setTimeout(function () {{
      btn.textContent = prev;
      btn.classList.remove("copied");
    }}, 1200);
  }});
}});
</script>
</body>
</html>
"""


def _html_job(r: dict[str, Any], slug: str, idx: int, anchor: str) -> str:
    paths = job_paths(slug)
    loc = html.escape(job_location(slug))
    apply = str(r.get("url") or "")
    status = str(r.get("status") or "")
    badge_cls = (
        "badge-tailored"
        if status == "tailored"
        else "badge-skipped"
        if status in {"skipped_fit", "skipped_duplicate", "skipped_term"}
        else "badge-failed"
        if "fail" in status
        else "badge-other"
    )
    company = html.escape(str(r.get("company") or ""))
    title = html.escape(str(r.get("title") or ""))
    loc_html = f" · {loc}" if loc else ""

    apply_btn = (
        f'<a class="btn btn-apply" href="{html.escape(apply)}" target="_blank" rel="noopener">Apply</a>'
        if apply
        else '<span class="btn btn-ghost is-missing">No apply URL</span>'
    )
    if paths["pdf"].exists():
        pdf_href = html.escape(_rel(paths["pdf"], REPORTS_DIR))
        pdf_btn = f'<a class="btn btn-pdf" href="{pdf_href}">Resume PDF</a>'
        pdf_path = html.escape(str(paths["pdf"]))
    else:
        pdf_btn = '<span class="btn btn-ghost is-missing">No PDF yet</span>'
        pdf_path = ""
    folder_href = html.escape(_rel(paths["folder"], REPORTS_DIR)) if paths["folder"].exists() else ""
    folder_btn = (
        f'<a class="btn btn-ghost" href="{folder_href}">Folder</a>' if folder_href else ""
    )
    answers_btn = ""
    if paths["answers"].exists():
        answers_btn = f'<a class="btn btn-ghost" href="{html.escape(_rel(paths["answers"], REPORTS_DIR))}">Answers.md</a>'

    items = parse_answers_md(paths["answers"])
    needs = [it for it in items if it["state"] == "needs"]
    needs_box = ""
    if needs:
        names = "; ".join(html.escape(it["prompt"]) for it in needs)
        needs_box = f'<div class="needs-box"><strong>Fill these yourself:</strong> {names}</div>'

    rows = []
    copy_all_parts = []
    all_id = f"all-{idx}"
    for it in items:
        aid = f"a-{idx}-{it['n']}"
        state = it["state"]
        req = "required" if it["required"] else "optional"
        tag = state if state != "ready" else req
        prompt = html.escape(it["prompt"])
        if state == "upload" and paths["pdf"].exists() and not it["answer"].lower().startswith("dear ") and "cover" not in it["prompt"].lower():
            body = f"Attach {paths['pdf'].name}"
        else:
            body = it["answer"] or ""
        if state in {"ready", "optional"} or (state == "upload" and "cover" in it["prompt"].lower()):
            copy_all_parts.append(f"{it['prompt']}\n{body}")
        rows.append(
            f'<div class="row {html.escape(state)}">'
            f'<div><div class="prompt">{it["n"]}. {prompt} <span class="tag">{html.escape(tag)}</span></div>'
            f'<pre class="answer" id="{aid}">{html.escape(body)}</pre></div>'
            f'<button type="button" class="copy" data-copy="{aid}">Copy</button></div>'
        )
    all_text = "\n\n".join(copy_all_parts)
    rows_html = "".join(rows) if rows else "<p class='muted'>No form questions captured. Use Apply and fill by hand.</p>"
    copy_all = ""
    if all_text:
        copy_all = (
            f'<button type="button" class="btn btn-ghost copy-all" data-copy="{all_id}">Copy all ready answers</button>'
            f'<pre class="answer" id="{all_id}" hidden>{html.escape(all_text)}</pre>'
        )
    path_line = f'<div class="path">{pdf_path}</div>' if pdf_path else ""

    return f"""
<article class="job" id="{anchor}">
  <h2>{company} — {title}<span class="badge {badge_cls}">{html.escape(status)}</span></h2>
  <div class="meta">{loc_html.strip(" ·") or html.escape("applications/" + slug + "/")}</div>
  <div class="actions">{apply_btn}{pdf_btn}{folder_btn}{answers_btn}</div>
  {path_line}
  {needs_box}
  {copy_all}
  <div class="qa">{rows_html}</div>
</article>
"""


if __name__ == "__main__":
    import json as _json
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    cfg = _json.loads((Path(__file__).resolve().parent / "config.json").read_text())
    seen = _json.loads((Path(__file__).resolve().parent / "state" / "seen.json").read_text())
    leftover = []
    qpath = Path(__file__).resolve().parent / "state" / "queue.json"
    if qpath.exists():
        leftover = _json.loads(qpath.read_text())
    rows = collect_today(seen)
    path = write_daily_report(cfg, rows, leftover, False, print)
    print(path)
