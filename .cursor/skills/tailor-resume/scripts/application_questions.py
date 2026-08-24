#!/usr/bin/env python3
"""Normalize ATS application questions and draft answers from profile.json."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

PROFILE_PATH = Path(__file__).resolve().parent.parent / "profile.json"

SKIP_LABELS = re.compile(
    r"^(resume/cv|resume|cv|cover letter)$",
    re.I,
)
CHROME_PROMPT_RE = re.compile(
    r"cookie|sign in|log in|privacy policy|subscribe|newsletter|"
    r"job alert|email me about|search jobs|^search$|^language$|"
    r"select language|site language|manage preferences",
    re.I,
)
APPLY_CTA_RE = re.compile(
    r"(start\s+(your\s+)?application|"
    r"begin\s+application|"
    r"apply\s+for\s+this|"
    r"\bapply(\s+now|\s+here|\s+manually|\s+online)?\b|"
    r"i('|’)m\s+interested)",
    re.I,
)
SUBMIT_CTA_RE = re.compile(
    r"submit|send\s+application|save\s+and\s+continue|^next$|^continue$",
    re.I,
)
APPLY_HREF_RE = re.compile(
    r"/apply\b|/application\b|startapplication|applynow|apply-now|"
    r"candidateexperience/.*/apply",
    re.I,
)
DEMOGRAPHIC_RE = re.compile(
    r"gender|sex\b|ethnicity|race\b|hispanic|veteran|disability|lgbt|"
    r"pronoun|sexual orientation|gender identity|self-identif",
    re.I,
)
PROFILE_NAME_RE = re.compile(
    r"first_name|last_name|preferred_name|email|phone|linkedin|github|"
    r"website|portfolio|school|university|college|gpa|graduat",
    re.I,
)
SCREENING_RE = re.compile(
    r"sponsor|visa|authoriz|citizen|relocat|work (full-time|in the)|"
    r"export control|security clearance|available to|hear about|"
    r"legally (authori[sz]ed|able)|require sponsorship|work authorization",
    re.I,
)
WRITTEN_RE = re.compile(
    r"why |tell us |describe |explain |essay|motivat|interested in|"
    r"cover letter|what interests|walk us through|talk about",
    re.I,
)
CERTIFY_RE = re.compile(
    r"i (certify|understand|agree|acknowledge)|true and correct|privacy",
    re.I,
)

NEEDS_USER = "**Needs user** — not in master/resume.tex, master/bank.md, or profile.json. Do not guess."


def load_profile() -> dict[str, Any]:
    if not PROFILE_PATH.exists():
        return {}
    with PROFILE_PATH.open() as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def _field_type(fields: list[dict[str, Any]]) -> str:
    if not fields:
        return "unknown"
    raw = str(fields[0].get("type") or "unknown")
    mapping = {
        "input_text": "text",
        "textarea": "textarea",
        "input_file": "file",
        "multi_value_single_select": "select",
        "multi_value_multi_select": "multiselect",
        "input_hidden": "hidden",
        "input_checkbox": "checkbox",
    }
    return mapping.get(raw, raw)


def _options(fields: list[dict[str, Any]]) -> list[str]:
    if not fields:
        return []
    values = fields[0].get("values") or []
    out = []
    for v in values:
        if isinstance(v, dict):
            lab = v.get("label") or v.get("value")
            if lab is not None and str(lab) != "":
                out.append(str(lab))
        else:
            out.append(str(v))
    return out


def classify(prompt: str, qtype: str, name: str) -> str:
    blob = f"{prompt} {name}"
    if DEMOGRAPHIC_RE.search(blob):
        return "demographic"
    if qtype == "file" or re.match(r"^(resume/cv|resume|cv|cover letter)$", prompt.strip(), re.I):
        return "upload"
    if CERTIFY_RE.search(prompt) and qtype in {"select", "checkbox"}:
        return "certify"
    if qtype == "textarea" or (WRITTEN_RE.search(prompt) and qtype not in {"select", "multiselect"}):
        return "written"
    if SCREENING_RE.search(blob):
        return "screening"
    if PROFILE_NAME_RE.search(name) or PROFILE_NAME_RE.search(prompt):
        return "profile"
    return "other"


def normalize_greenhouse(raw_questions: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(raw_questions, list):
        return out
    for item in raw_questions:
        if not isinstance(item, dict):
            continue
        fields = item.get("fields") or []
        if not isinstance(fields, list):
            fields = []
        prompt = html_plain(str(item.get("label") or item.get("description") or "")).strip()
        if not prompt:
            continue
        name = ""
        if fields and isinstance(fields[0], dict):
            name = str(fields[0].get("name") or "")
        qtype = _field_type(fields)
        if qtype == "hidden":
            continue
        desc = html_plain(str(item.get("description") or "")).strip()
        q = {
            "prompt": prompt,
            "required": bool(item.get("required")),
            "type": qtype,
            "options": _options(fields),
            "name": name,
            "description": desc,
        }
        q["kind"] = classify(prompt, qtype, name)
        out.append(q)
    return out


def html_plain(raw: str) -> str:
    from html import unescape

    text = unescape(raw)
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_questions_from_html(html: str) -> list[dict[str, Any]]:
    """Best-effort labels + textarea/select/input from an apply form."""
    if not html:
        return []
    questions: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(prompt: str, qtype: str, required: bool, options: list[str] | None = None) -> None:
        prompt = html_plain(prompt)
        prompt = re.sub(r"\s*\*$", "", prompt).strip()
        if len(prompt) < 3 or len(prompt) > 400:
            return
        key = prompt.lower()
        if key in seen:
            return
        if CHROME_PROMPT_RE.search(key):
            return
        seen.add(key)
        q = {
            "prompt": prompt,
            "required": required,
            "type": qtype,
            "options": options or [],
            "name": "",
            "description": "",
        }
        q["kind"] = classify(prompt, qtype, "")
        questions.append(q)

    for m in re.finditer(
        r'(?is)<label\b([^>]*)>(.*?)</label>',
        html,
    ):
        attrs, inner = m.group(1), m.group(2)
        required = "required" in attrs.lower() or "*" in inner
        text = html_plain(inner)
        if text:
            add(text, "text", required)

    for m in re.finditer(r"(?is)<textarea\b([^>]*)>(.*?)</textarea>", html):
        attrs = m.group(1)
        ph = re.search(r'placeholder=["\']([^"\']+)', attrs, re.I)
        lab = re.search(r'aria-label=["\']([^"\']+)', attrs, re.I)
        prompt = (lab.group(1) if lab else "") or (ph.group(1) if ph else "Written response")
        add(prompt, "textarea", "required" in attrs.lower())

    for m in re.finditer(r"(?is)<select\b([^>]*)>(.*?)</select>", html):
        attrs, body = m.group(1), m.group(2)
        lab = re.search(r'aria-label=["\']([^"\']+)', attrs, re.I)
        opts = [html_plain(o) for o in re.findall(r"(?is)<option[^>]*>(.*?)</option>", body)]
        opts = [o for o in opts if o and not re.match(r"^(select|choose)", o, re.I)]
        add(lab.group(1) if lab else "Select an option", "select", "required" in attrs.lower(), opts[:30])

    for m in re.finditer(r"(?is)<input\b([^>]*)/?>", html):
        attrs = m.group(1)
        itype = (_html_attr(attrs, "type") or "text").lower()
        if itype in {"hidden", "submit", "button", "image", "reset", "search"}:
            continue
        prompt = (
            _html_attr(attrs, "aria-label")
            or _html_attr(attrs, "placeholder")
            or _html_attr(attrs, "title")
            or _humanize_name(_html_attr(attrs, "name") or _html_attr(attrs, "id") or "")
        )
        if prompt:
            add(prompt, itype if itype != "text" else "text", "required" in attrs.lower())

    return questions[:80]


def _html_attr(attrs: str, name: str) -> str:
    m = re.search(rf'{name}=["\']([^"\']+)', attrs, re.I)
    return m.group(1).strip() if m else ""


def _humanize_name(name: str) -> str:
    text = re.sub(r"[_\-\[\]0-9]+", " ", name or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:80]


def is_apply_cta(text: str, href: str = "") -> bool:
    """True for Start Application / Apply, never for Submit on an open form."""
    t = re.sub(r"\s+", " ", (text or "")).strip()
    h = href or ""
    if SUBMIT_CTA_RE.search(t):
        return False
    if re.search(r"sign\s*in|log\s*in|create\s+account", t, re.I):
        return False
    if re.search(r"linkedin|indeed|glassdoor|google", t, re.I) and re.search(
        r"apply with|autofill", t, re.I
    ):
        return False
    if t and APPLY_CTA_RE.search(t):
        return True
    return bool(h) and bool(APPLY_HREF_RE.search(h))


def find_apply_hrefs(html: str, base: str) -> list[str]:
    """Apply / Start Application links in listing HTML (no click)."""
    if not html or not base:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r'(?is)<a\b([^>]*)>(.*?)</a>', html):
        attrs, inner = m.group(1), m.group(2)
        href = _html_attr(attrs, "href")
        if not href or href.startswith(("javascript:", "mailto:", "#")):
            continue
        text = html_plain(inner) or _html_attr(attrs, "aria-label")
        if not is_apply_cta(text, href):
            continue
        abs_url = urllib_join(base, href)
        if abs_url in seen or abs_url.split("#")[0] == base.split("#")[0]:
            continue
        seen.add(abs_url)
        found.append(abs_url)
    for suffix in ("/apply", "/application"):
        if "?" in base:
            continue
        candidate = base.rstrip("/") + suffix
        if candidate not in seen:
            found.append(candidate)
    return found[:6]


def urllib_join(base: str, href: str) -> str:
    from urllib.parse import urljoin

    return urljoin(base, href)


def questions_look_real(questions: list[dict[str, Any]] | None) -> bool:
    """False for empty, cookie, job-alert, or language-chrome-only field sets."""
    if not questions:
        return False
    real = [
        q
        for q in questions
        if not CHROME_PROMPT_RE.search(str(q.get("prompt") or ""))
    ]
    if any(
        q.get("kind") == "written" or str(q.get("type") or "") == "textarea"
        for q in real
    ):
        return True
    if any(q.get("kind") in {"screening", "upload", "certify"} for q in real):
        return True
    return len(real) >= 2


def merge_questions(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for q in group or []:
            key = str(q.get("prompt") or "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(q)
    return out[:80]


def looks_like_login_wall(
    questions: list[dict[str, Any]],
    page_text: str = "",
) -> bool:
    blob = " ".join(str(q.get("prompt") or "") for q in questions) + " " + (page_text or "")
    types = {str(q.get("type") or "").lower() for q in questions}
    if "password" in types or re.search(r"\bpassword\b", blob, re.I):
        if re.search(r"sign in|log in|create account|forgot password", blob, re.I):
            return True
    return False


def questions_from_forms_json(raw: Any) -> list[dict[str, Any]]:
    """Normalize `$B forms` JSON into the scraper question shape."""
    forms = raw
    if isinstance(raw, str):
        try:
            forms = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if isinstance(forms, dict):
        forms = forms.get("forms") or forms.get("fields") or [forms]
    if not isinstance(forms, list):
        return []
    questions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for form in forms:
        fields = form.get("fields") if isinstance(form, dict) else None
        if fields is None and isinstance(form, dict) and form.get("name"):
            fields = [form]
        if not isinstance(fields, list):
            continue
        for field in fields:
            if not isinstance(field, dict):
                continue
            ftype = str(field.get("type") or "text").lower()
            if ftype in {"hidden", "submit", "button", "image", "reset"}:
                continue
            prompt = (
                str(field.get("label") or field.get("prompt") or "")
                or str(field.get("placeholder") or "")
                or _humanize_name(str(field.get("name") or field.get("id") or ""))
            ).strip()
            if len(prompt) < 2 or CHROME_PROMPT_RE.search(prompt.lower()):
                continue
            key = prompt.lower()
            if key in seen:
                continue
            seen.add(key)
            options = field.get("options") or field.get("values") or []
            opts: list[str] = []
            for o in options:
                if isinstance(o, dict):
                    lab = o.get("label") or o.get("text") or o.get("value")
                    if lab is not None and str(lab) != "":
                        opts.append(str(lab))
                elif o:
                    opts.append(str(o))
            q = {
                "prompt": prompt,
                "required": bool(field.get("required") or field.get("isRequired")),
                "type": ftype,
                "options": opts[:30],
                "name": str(field.get("name") or ""),
                "description": "",
            }
            q["kind"] = classify(prompt, ftype, str(field.get("name") or ""))
            questions.append(q)
    return questions[:80]


def _match_option(options: list[str], *candidates: str) -> str | None:
    if not options:
        return None
    lowered = [(o, o.lower()) for o in options]
    for cand in candidates:
        c = cand.lower()
        for orig, low in lowered:
            if c == low or c in low or low in c:
                return orig
    return None


def suggest_answer(q: dict[str, Any], profile: dict[str, Any] | None = None) -> str:
    profile = profile or load_profile()
    kind = q.get("kind") or classify(str(q.get("prompt") or ""), str(q.get("type") or ""), str(q.get("name") or ""))
    prompt = str(q.get("prompt") or "")
    name = str(q.get("name") or "")
    qtype = str(q.get("type") or "")
    options = list(q.get("options") or [])
    blob = f"{prompt} {name}".lower()

    if kind == "demographic":
        return "Leave blank / fill on the form. Do not auto-submit EEO self-identification."

    if kind == "upload":
        if re.search(r"cover letter", blob):
            return "Optional upload. Use the drafted letter in this file if the form has a text box; otherwise paste into the cover-letter field."
        return "Upload `resume.pdf` from this application folder."

    if kind == "certify":
        yes = _match_option(options, "Yes", "I agree", "Agree")
        return yes or "Yes"

    if re.search(r"first name|preferred (first )?name", blob) and "last" not in blob:
        return str(profile.get("preferred_name") or profile.get("first_name") or "")
    if re.search(r"last name|surname|family name", blob):
        return str(profile.get("last_name") or "")
    if "email" in blob:
        return str(profile.get("email") or "")
    if "phone" in blob:
        return str(profile.get("phone") or "")
    if "linkedin" in blob:
        return str(profile.get("linkedin") or "")
    if re.search(r"github|website|portfolio|personal url", blob):
        return str(profile.get("github") or profile.get("website") or "")
    if re.search(r"school|university|college", blob) and "high school" not in blob:
        return str(profile.get("school") or "")
    if "gpa" in blob:
        return str(profile.get("gpa") or "")
    if "major" in blob or "degree" in blob:
        major = profile.get("major") or ""
        degree = profile.get("degree") or ""
        return ", ".join(p for p in (degree, major) if p)

    if re.search(r"graduat", blob):
        yes_no = {o.lower() for o in options} <= {"yes", "no", "not applicable", "n/a", "unsure"}
        if yes_no and options:
            return NEEDS_USER
        graduation = str(profile.get("graduation") or "").strip()
        if not graduation:
            return NEEDS_USER
        year_m = re.search(r"(20\d{2})", graduation)
        year = year_m.group(1) if year_m else ""
        picked = _match_option(
            options,
            graduation,
            f"Summer {year}" if year else "",
            f"Spring {year}" if year else "",
            year,
        )
        if picked:
            return picked
        if options:
            return f"{graduation} — pick the closest option among: {', '.join(options[:8])}"
        return graduation

    if re.search(r"programming languages|languages do you have", blob) and options:
        lang_set = {str(x).lower() for x in (profile.get("languages") or [])}
        extra = set()
        if "c++" in lang_set:
            extra.add("cpp")
        if "javascript" in lang_set:
            extra.add("js")
        if "go" in lang_set or "golang" in lang_set:
            extra.update({"go", "golang"})
        hits = [
            opt
            for opt in options
            if opt.lower().strip() in lang_set or opt.lower().strip() in extra
        ]
        if hits:
            return ", ".join(hits)
        return NEEDS_USER

    if kind == "screening" or SCREENING_RE.search(blob):
        citizen = bool(profile.get("us_citizen"))
        authorized = bool(profile.get("work_authorized_us") or citizen)
        needs_spon = profile.get("needs_sponsorship")
        relocate = bool(profile.get("willing_to_relocate"))
        available = bool(profile.get("available_for_internship"))

        if options and any(
            re.search(r"no restriction|sponsorship in the future|need sponsorship now", o, re.I)
            for o in options
        ):
            if authorized and needs_spon is False:
                return (
                    _match_option(
                        options,
                        "Yes, no restriction.",
                        "Yes, I am authorized to work without sponsorship",
                        "U.S. Citizen",
                        "United States Citizen",
                    )
                    or "Yes, no restriction."
                )

        if re.search(r"sponsor|visa|h-1b|opt\b|cpt\b", blob):
            if needs_spon is True:
                return _match_option(options, "Yes") or "Yes"
            if needs_spon is False:
                return _match_option(options, "No") or "No"
            return NEEDS_USER

        if re.search(r"citizen", blob):
            if citizen:
                return _match_option(options, "Yes", "U.S. Citizen", "United States") or "Yes"
            return NEEDS_USER

        if re.search(r"authoriz|legally", blob):
            if authorized:
                return _match_option(options, "Yes", "Yes, no restriction.") or "Yes"
            return NEEDS_USER

        if re.search(r"relocat|on-?site|in the office|hybrid", blob):
            if relocate:
                return _match_option(options, "Yes") or "Yes"
            return NEEDS_USER

        if re.search(r"available to work|able to work full-time|can you work", blob):
            if available:
                return _match_option(options, "Yes") or "Yes"
            return NEEDS_USER

        return NEEDS_USER

    if kind == "written" or qtype == "textarea":
        return (
            "DRAFT. Rewrite from master/resume.tex, master/bank.md, and writing.md. "
            "Novel-like flowing prose. No resume recap, no em dashes, avoid colons, "
            "no citizenship/relocation in cover letters. No invented facts."
        )

    if kind == "profile":
        return NEEDS_USER

    return NEEDS_USER if q.get("required") else "(optional — skip unless relevant)"


def render_answers_md(
    company: str,
    role: str,
    url: str,
    questions: list[dict[str, Any]],
    profile: dict[str, Any] | None = None,
) -> str:
    profile = profile or load_profile()
    lines = [
        f"# Application answers — {company} — {role}",
        "",
        f"- Source: {url}",
        "- Facts: `master/resume.tex`, `master/bank.md`, `.cursor/skills/tailor-resume/profile.json`",
        "- **Needs user** means the fact is missing. Do not invent it.",
        "",
    ]
    if not questions:
        lines += [
            "_No application-form questions were found on the posting. If the apply page is login-walled, paste the questions here and regenerate._",
            "",
        ]
        return "\n".join(lines)

    for i, q in enumerate(questions, 1):
        req = "required" if q.get("required") else "optional"
        kind = q.get("kind") or "other"
        lines.append(f"## {i}. {q.get('prompt')} ({req}, {kind})")
        if q.get("description"):
            lines.append("")
            lines.append(str(q["description"]))
        if q.get("options"):
            lines.append("")
            lines.append("Options: " + "; ".join(str(o) for o in q["options"]))
        lines.append("")
        lines.append(suggest_answer(q, profile))
        lines.append("")
    return "\n".join(lines)


def questions_summary(questions: list[dict[str, Any]]) -> str:
    if not questions:
        return "_None found on the posting._"
    lines = []
    for q in questions:
        flag = "required" if q.get("required") else "optional"
        kind = q.get("kind") or "other"
        lines.append(f"- {q.get('prompt')} ({flag}, {kind})")
    return "\n".join(lines)
