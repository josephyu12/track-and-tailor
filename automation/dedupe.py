#!/usr/bin/env python3
"""Treat same company + same intern role as one job (ignore location / listing id)."""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

STATE = Path(__file__).resolve().parent / "state"
DELETED_PATH = STATE / "deleted.json"
SCRAPE = Path(__file__).resolve().parents[1] / ".cursor" / "skills" / "tailor-resume" / "scripts"

sys.path.insert(0, str(SCRAPE))
from check_resume import submit_pdf_path  # noqa: E402

GENERIC_EXTRA = {
    "college",
    "corporate",
    "information",
    "it",
    "locations",
    "multiple",
    "several",
    "team",
    "teams",
    "technology",
    "various",
}
# Only ignore ML/AI extras when the short title is already an ML/AI role.
ML_EXTRA = {"ai", "artificial", "intelligence", "learning", "machine", "ml"}

FLUFF_SEGMENT = re.compile(
    r"""^(
        multiple\s+teams | various\s+teams | several\s+teams |
        college\s+to\s+corporate(\s+it)? |
        information\s+technology |
        campus\s+undergraduate(\s+summer)?(\s+intern(ship)?(\s+program)?)? |
        undergraduate\s+summer\s+intern(ship)?(\s+program)? |
        internship\s+program |
        multiple\s+locations | various\s+locations | several\s+locations
    )$""",
    re.I | re.X,
)

CORP_SUFFIX = re.compile(r"\b(inc|llc|ltd|corp|corporation|incorporated|the)\b\.?", re.I)
TRACKING_QS = {
    "gh_src",
    "icims",
    "simplify",
    "source",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
    "ref",
}


def normalize_company(company: str) -> str:
    c = CORP_SUFFIX.sub(" ", str(company or "").lower())
    c = re.sub(r"[^a-z0-9]+", " ", c)
    return re.sub(r"\s+", " ", c).strip()


def normalize_title(title: str) -> str:
    parts = re.split(r"\s*[-–—|:]\s*", str(title or ""))
    kept: list[str] = []
    seen_tokens: set[str] = set()
    for raw in parts:
        p = re.sub(r"\s+", " ", raw.strip().lower())
        p = re.sub(r"\(?\b(summer|fall|spring|winter)\s*2027\b\)?", "", p).strip(" ,")
        if not p or FLUFF_SEGMENT.match(p):
            continue
        toks = set(re.findall(r"[a-z0-9]+", p))
        if toks and toks <= seen_tokens:
            continue
        kept.append(p)
        seen_tokens |= toks
    t = " ".join(kept) or str(title or "").lower()
    t = t.replace("co-op", "intern").replace("co op", "intern")
    t = re.sub(r"\binternship\b", "intern", t)
    t = re.sub(r"\b2027\b", "", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    t = re.sub(r"(\bintern\b\s*)+", "intern ", t)
    return re.sub(r"\s+", " ", t).strip()


def exact_apply_url(url: str) -> str:
    """Raw apply URL. Whitespace stripped; query string kept as-is."""
    raw = str(url or "").strip()
    if not raw.startswith("http"):
        return ""
    return raw


def canonical_url(url: str) -> str:
    raw = exact_apply_url(url)
    if not raw:
        return ""
    p = urllib.parse.urlsplit(raw)
    query = [
        (k, v)
        for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
        if k.lower() not in TRACKING_QS
    ]
    path = p.path.rstrip("/").lower()
    netloc = p.netloc.lower()
    return urllib.parse.urlunsplit((p.scheme.lower(), netloc, path, urllib.parse.urlencode(query), ""))


def titles_equivalent(a: str, b: str) -> bool:
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    short, long = (na, nb) if len(na) <= len(nb) else (nb, na)
    if not long.startswith(short + " "):
        return False
    extra = long[len(short) :].split()
    if not extra:
        return False
    short_toks = set(short.split())
    allowed = set(GENERIC_EXTRA)
    if short_toks & {"ai", "ml", "machine", "learning", "artificial", "intelligence"}:
        allowed |= ML_EXTRA
    return all(tok in allowed for tok in extra)


def same_job(company_a: str, title_a: str, url_a: str, company_b: str, title_b: str, url_b: str) -> bool:
    cu, cv = canonical_url(url_a), canonical_url(url_b)
    if cu and cv and cu == cv:
        return True
    if normalize_company(company_a) != normalize_company(company_b):
        return False
    return titles_equivalent(title_a, title_b)


def identity_keys(company: str, title: str, url: str) -> list[str]:
    keys: list[str] = []
    cu = canonical_url(url)
    if cu:
        keys.append("url:" + cu)
    ck, tk = normalize_company(company), normalize_title(title)
    if ck and tk:
        keys.append("ct:" + ck + "|" + tk)
    return keys


def parse_job_identity(path: Path) -> dict[str, str] | None:
    if not path.exists():
        return None
    company, role = path.parent.name, ""
    url = ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[:20]:
        if line.startswith("# "):
            title = line[2:].strip()
            if " — " in title:
                company, role = title.split(" — ", 1)
            else:
                company = title
        elif line.startswith("- Source:"):
            url = line.split(":", 1)[1].strip()
        elif line.startswith("- Slug:"):
            pass
    return {"company": company, "title": role, "url": url, "slug": path.parent.name}


class DuplicateIndex:
    def __init__(self) -> None:
        self.keys: dict[str, str] = {}
        self.exact_urls: dict[str, str] = {}
        self.rows: list[tuple[str, str, str, str]] = []

    def add(self, company: str, title: str, url: str, slug: str) -> None:
        if not slug:
            return
        cu = canonical_url(url)
        if cu:
            self.exact_urls.setdefault(cu, slug)
        for key in identity_keys(company, title, url):
            self.keys.setdefault(key, slug)
        self.rows.append((company, title, url, slug))

    def match_exact_url(self, url: str) -> str | None:
        """Same apply link: ignore tracking params, trailing slash, host case."""
        cu = canonical_url(url)
        if not cu:
            return None
        return self.exact_urls.get(cu)

    def match(self, company: str, title: str, url: str) -> str | None:
        hit = self.match_exact_url(url)
        if hit:
            return hit
        for key in identity_keys(company, title, url):
            if key in self.keys:
                return self.keys[key]
        for c, t, u, slug in self.rows:
            if same_job(company, title, url, c, t, u):
                return slug
        return None

    def claim(self, company: str, title: str, url: str, slug: str) -> None:
        self.add(company, title, url, slug)


def load_deleted() -> dict[str, Any]:
    if not DELETED_PATH.exists():
        return {}
    try:
        data = json.loads(DELETED_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def remember_deleted(slug: str, company: str, title: str, url: str) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    data = load_deleted()
    data[slug] = {
        "slug": slug,
        "company": company,
        "title": title,
        "url": url,
        "at": datetime.now().isoformat(timespec="seconds"),
    }
    DELETED_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def index_from_applications(
    apps: Path, *, require_pdf: bool = False
) -> DuplicateIndex:
    idx = DuplicateIndex()
    if not apps.is_dir():
        return idx
    for folder in apps.iterdir():
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        if require_pdf and not submit_pdf_path(folder).is_file():
            continue
        ident = parse_job_identity(folder / "job.md")
        if ident:
            idx.add(ident["company"], ident["title"], ident["url"], ident["slug"])
    return idx


def index_from_seen(
    seen: dict[str, Any],
    apps: Path | None = None,
    *,
    require_pdf: bool = False,
) -> DuplicateIndex:
    idx = index_from_applications(apps, require_pdf=require_pdf) if apps else DuplicateIndex()
    keep = {"tailored", "scraped", "skipped_duplicate"}
    for rec in (seen or {}).values():
        if not isinstance(rec, dict) or rec.get("status") not in keep:
            continue
        slug = str(rec.get("slug") or "")
        if require_pdf and (not slug or not apps or not submit_pdf_path(apps / slug).is_file()):
            continue
        idx.add(
            str(rec.get("company") or ""),
            str(rec.get("title") or ""),
            str(rec.get("url") or ""),
            slug,
        )
    for rec in load_deleted().values():
        if not isinstance(rec, dict):
            continue
        idx.add(
            str(rec.get("company") or ""),
            str(rec.get("title") or ""),
            str(rec.get("url") or ""),
            str(rec.get("slug") or ""),
        )
    return idx


def _row_rank(row: dict[str, Any]) -> tuple:
    slug = str(row.get("slug") or "")
    title = str(row.get("title") or "").lower()
    program_title = (
        1 if ("internship program" in title or "campus undergraduate" in title) else 0
    )
    fit = row.get("fit") if isinstance(row.get("fit"), dict) else {}
    try:
        fit_score = float(fit.get("score") or 0)
    except (TypeError, ValueError):
        fit_score = 0.0
    return (
        0 if row.get("applied") else 1,
        0 if row.get("pdf") else 1,
        0 if row.get("keep") else 1,
        0 if fit_score >= 0.4 else 1,
        program_title,
        0 if not re.search(r"-[0-9a-f]{8}$", slug) and "custom" not in slug else 1,
        len(slug),
        slug,
    )


def collapse_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for row in rows:
        hit = None
        for existing in kept:
            if same_job(
                str(row.get("company") or ""),
                str(row.get("title") or ""),
                str(row.get("url") or ""),
                str(existing.get("company") or ""),
                str(existing.get("title") or ""),
                str(existing.get("url") or ""),
            ):
                hit = existing
                break
        if hit is None:
            row = dict(row)
            row["dups"] = []
            kept.append(row)
            continue
        extras: list[dict[str, Any]] = hit.setdefault("dups", [])
        if _row_rank(row) < _row_rank(hit):
            extras.append({k: hit[k] for k in hit if k != "dups"})
            for key, val in row.items():
                if key != "dups":
                    hit[key] = val
        else:
            extras.append(row)
    for row in kept:
        dups = row.get("dups") or []
        locs = []
        for extra in dups:
            loc = (extra.get("location") or "").strip()
            if loc and loc not in locs and loc != (row.get("location") or "").strip():
                locs.append(loc)
        row["dup_count"] = len(dups)
        row["dup_locations"] = locs
    return kept
