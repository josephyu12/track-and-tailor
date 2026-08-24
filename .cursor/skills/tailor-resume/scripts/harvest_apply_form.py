#!/usr/bin/env python3
"""Open a job posting in gstack browse, click Start Application / Apply, extract form fields.

Never submits an application. Never fills credentials. Stops at login walls.

Usage:
  python3 harvest_apply_form.py URL
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from application_questions import (
    extract_questions_from_html,
    looks_like_login_wall,
    merge_questions,
    questions_from_forms_json,
    questions_look_real,
)

BROWSE_CANDIDATES = (
    Path.home() / ".claude/skills/gstack/browse/dist/browse",
    Path.home() / ".codex/skills/gstack/browse/dist/browse",
)

UNTRUSTED_RE = re.compile(
    r"(?:═══ BEGIN UNTRUSTED[^\n]*\n|--- BEGIN UNTRUSTED[^\n]*\n)"
    r"(.*?)"
    r"(?:\n═══ END UNTRUSTED[^\n]*|\n--- END UNTRUSTED[^\n]*)",
    re.S,
)

CLICK_JS = r"""
(() => {
  const skip = /submit|send application|save and continue|create account|sign\s*in|log\s*in|^next$|^continue$|cookie settings/i;
  const cookie = /accept (all )?cookies|allow cookies|accept all$/i;
  const scoreOf = (text, href) => {
    const t = (text || '').replace(/\s+/g, ' ').trim();
    const h = (href || '').toLowerCase();
    if (!t && !h) return -1;
    if (skip.test(t)) return -1;
    if (/linkedin|indeed|glassdoor|google/i.test(t) && /apply with|autofill/i.test(t)) return -1;
    let s = -1;
    if (/start\s+(your\s+)?application/i.test(t)) s = 100;
    else if (/apply\s+manually/i.test(t)) s = 90;
    else if (/apply\s+now/i.test(t)) s = 80;
    else if (/apply\s+for\s+this/i.test(t)) s = 75;
    else if (/i('|’)m\s+interested/i.test(t)) s = 70;
    else if (/begin\s+application/i.test(t)) s = 85;
    else if (/^apply$/i.test(t)) s = 50;
    else if (/\bapply\b/i.test(t)) s = 40;
    if (/\/apply\b|startapplication|applynow/i.test(h) && s < 40) s = 35;
    return s;
  };

  const cookieBtns = [...document.querySelectorAll('button, [role=button], a')];
  for (const el of cookieBtns) {
    const t = (el.innerText || el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
    if (cookie.test(t) && t.length < 40) {
      el.click();
      break;
    }
  }

  const els = [...document.querySelectorAll('a, button, [role=button], input[type=button], input[type=submit]')];
  let best = null;
  let bestScore = 0;
  for (const el of els) {
    const text = el.innerText || el.value || el.getAttribute('aria-label') || '';
    const href = el.href || el.getAttribute('href') || '';
    const s = scoreOf(text, href);
    if (s > bestScore) {
      best = el;
      bestScore = s;
    }
  }
  if (!best) return JSON.stringify({clicked: false, score: 0});
  best.click();
  return JSON.stringify({
    clicked: true,
    text: ((best.innerText || best.value || '') + '').replace(/\s+/g, ' ').trim().slice(0, 80),
    score: bestScore
  });
})()
"""


def find_browse() -> Path | None:
    for path in BROWSE_CANDIDATES:
        if path.is_file() and os.access(path, os.X_OK):
            return path
    return None


def unwrap(text: str) -> str:
    if not text:
        return ""
    m = UNTRUSTED_RE.search(text)
    return (m.group(1) if m else text).strip()


def run_browse(args: list[str], timeout: int = 45) -> tuple[int, str]:
    binary = find_browse()
    if binary is None:
        raise FileNotFoundError("gstack browse binary not found")
    proc = subprocess.run(
        [str(binary), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, unwrap(proc.stdout or "")


def _parse_json(blob: str) -> Any:
    text = unwrap(blob)
    if not text:
        return None
    start = text.find("{")
    start_arr = text.find("[")
    if start == -1 or (start_arr != -1 and start_arr < start):
        start = start_arr
    if start == -1:
        return None
    try:
        return json.loads(text[start:])
    except json.JSONDecodeError:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None


def harvest_apply_form(url: str, timeout: int = 60) -> dict[str, Any]:
    """Click Start Application / Apply and return {questions, clicked, login_walled, error}."""
    out: dict[str, Any] = {
        "url": url,
        "questions": [],
        "clicked": None,
        "login_walled": False,
        "error": None,
    }
    if not find_browse():
        out["error"] = "browse_not_found"
        return out
    deadline = time.time() + max(15, timeout)
    js_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".js", prefix="apply-click-", dir="/tmp", delete=False
        ) as fh:
            fh.write(CLICK_JS)
            js_path = fh.name

        run_browse(["goto", url], timeout=min(40, max(10, int(deadline - time.time()))))
        try:
            run_browse(["wait", "--load"], timeout=20)
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            pass
        time.sleep(1.0)

        clicks: list[str] = []
        for _ in range(2):
            if time.time() > deadline - 8:
                break
            code, raw = run_browse(["eval", js_path], timeout=20)
            payload = _parse_json(raw) if code == 0 else None
            if isinstance(payload, dict) and payload.get("clicked"):
                label = str(payload.get("text") or "Apply")
                clicks.append(label)
                time.sleep(1.5)
                try:
                    run_browse(["wait", "--load"], timeout=20)
                except (subprocess.TimeoutExpired, subprocess.SubprocessError):
                    pass
            else:
                break
        if clicks:
            out["clicked"] = " -> ".join(clicks)

        forms_raw = ""
        html = ""
        page_text = ""
        try:
            _c, forms_raw = run_browse(["forms"], timeout=15)
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            pass
        try:
            _c, html = run_browse(["html"], timeout=20)
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            pass
        try:
            _c, page_text = run_browse(["text"], timeout=15)
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            pass
        try:
            _c, current = run_browse(["url"], timeout=10)
            if current.startswith("http"):
                out["url"] = current.split()[0]
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            pass

        from_forms = questions_from_forms_json(_parse_json(forms_raw) or forms_raw)
        from_html = extract_questions_from_html(html)
        questions = merge_questions(from_forms, from_html)
        out["questions"] = questions
        out["login_walled"] = looks_like_login_wall(questions, page_text or html)
        if not questions_look_real(questions) and not out["login_walled"] and not out["clicked"]:
            out["error"] = out["error"] or "no_apply_cta"
    except FileNotFoundError:
        out["error"] = "browse_not_found"
    except subprocess.TimeoutExpired:
        out["error"] = "timeout"
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    finally:
        if js_path:
            try:
                os.unlink(js_path)
            except OSError:
                pass
    return out


def main(argv: list[str]) -> int:
    urls = [a for a in argv[1:] if a.strip() and not a.startswith("-")]
    if not urls:
        print("usage: harvest_apply_form.py URL", file=sys.stderr)
        return 2
    result = harvest_apply_form(urls[0])
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if (result.get("questions") or result.get("login_walled")) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
