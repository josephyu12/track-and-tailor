#!/usr/bin/env python3
"""Fetch a job posting URL and print JSON: company, role, location, jd_text.

Tries ATS APIs first (Greenhouse, Lever, Ashby, Apple, Workday, Oracle HCM),
then JSON-LD JobPosting, then stripped HTML. Stdlib only.

Usage:
  python3 scrape_jd.py URL
  python3 scrape_jd.py [--browser] URL [URL...]
"""

from __future__ import annotations

import html as htmlmod
import json
import re
import socket
import ssl
import sys
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from http.client import IncompleteRead, RemoteDisconnected
from typing import Any

from application_questions import (  # noqa: E402
    extract_questions_from_html,
    find_apply_hrefs,
    merge_questions,
    normalize_greenhouse,
    questions_look_real,
)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
TIMEOUT = 45
MIN_JD_CHARS = 280
FETCH_ATTEMPTS = 4
RETRY_HTTP = {408, 425, 429, 500, 502, 503, 504}
FETCH_EXCEPTIONS = (
    urllib.error.URLError,
    IncompleteRead,
    TimeoutError,
    socket.timeout,
    ConnectionError,
    ssl.SSLError,
    RemoteDisconnected,
    OSError,
)


def _fetch_once(
    url: str,
    accept: str,
    extra_headers: dict[str, str] | None = None,
) -> tuple[str, str, bytes]:
    headers = {
        "User-Agent": UA,
        "Accept": accept,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "identity",
        "Connection": "close",
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(
        url,
        headers=headers,
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        final = resp.geturl()
        ctype = resp.headers.get_content_type() or ""
        data = resp.read()
    return final, ctype, data


def fetch(
    url: str,
    accept: str = "*/*",
    attempts: int = FETCH_ATTEMPTS,
    pause: float = 1.2,
    headers: dict[str, str] | None = None,
) -> tuple[str, str, bytes]:
    """GET with retries. Truncated chunked responses are retried, then used if large enough."""
    last: BaseException | None = None
    partial: bytes = b""
    for attempt in range(max(1, attempts)):
        try:
            return _fetch_once(url, accept, extra_headers=headers)
        except urllib.error.HTTPError as e:
            last = e
            if e.code in RETRY_HTTP and attempt + 1 < attempts:
                time.sleep(pause * (attempt + 1))
                continue
            raise
        except IncompleteRead as e:
            last = e
            partial = bytes(e.partial or b"")
            if attempt + 1 < attempts:
                time.sleep(pause * (attempt + 1))
                continue
            if len(partial) >= 4096:
                return url, "text/html", partial
            raise
        except FETCH_EXCEPTIONS as e:
            last = e
            if attempt + 1 < attempts:
                time.sleep(pause * (attempt + 1))
                continue
            raise
    if last:
        raise last
    raise RuntimeError(f"fetch failed: {url}")


def fetch_text(
    url: str,
    accept: str = "*/*",
    headers: dict[str, str] | None = None,
) -> tuple[str, str]:
    final, ctype, data = fetch(url, accept=accept, headers=headers)
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return final, data.decode(enc)
        except UnicodeDecodeError:
            continue
    return final, data.decode("utf-8", errors="replace")


def fetch_json(url: str, headers: dict[str, str] | None = None) -> tuple[str, Any]:
    final, text = fetch_text(
        url, accept="application/json, text/plain, */*", headers=headers
    )
    return final, json.loads(text)


def strip_tags(raw: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", raw)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|li|h[1-6]|tr|section|article)>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = htmlmod.unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def html_to_text(fragment: str) -> str:
    text = htmlmod.unescape(fragment)
    if "&lt;" in text or "&#" in text:
        text = htmlmod.unescape(text)
    return strip_tags(text)


def extract_json_ld_jobs(html: str) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for m in re.finditer(
        r'(?is)<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
    ):
        blob = m.group(1).strip()
        if not blob:
            continue
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        nodes = data if isinstance(data, list) else [data]
        extra = []
        for node in nodes:
            if isinstance(node, dict) and "@graph" in node:
                graph = node["@graph"]
                if isinstance(graph, list):
                    extra.extend(graph)
        nodes = list(nodes) + extra
        for node in nodes:
            if not isinstance(node, dict):
                continue
            types = node.get("@type") or node.get("type") or ""
            if isinstance(types, list):
                types = " ".join(str(t) for t in types)
            if re.search(r"JobPosting", str(types), re.I):
                jobs.append(node)
    return jobs


def org_name(node: Any) -> str:
    if isinstance(node, dict):
        return str(node.get("name") or "").strip()
    if isinstance(node, str):
        return node.strip()
    return ""


def loc_name(node: Any) -> str:
    if isinstance(node, list) and node:
        return loc_name(node[0])
    if isinstance(node, str):
        return node.strip()
    if not isinstance(node, dict):
        return ""
    addr = node.get("address")
    if isinstance(addr, dict):
        parts = [
            addr.get("addressLocality"),
            addr.get("addressRegion"),
            addr.get("addressCountry"),
        ]
        return ", ".join(str(p) for p in parts if p)
    return str(node.get("name") or "").strip()


def from_jobposting(job: dict[str, Any], url: str) -> dict[str, Any]:
    desc = job.get("description") or ""
    if not isinstance(desc, str):
        desc = str(desc)
    return {
        "ok": True,
        "url": url,
        "ats": "jsonld",
        "company": org_name(job.get("hiringOrganization")),
        "role": str(job.get("title") or "").strip(),
        "location": loc_name(job.get("jobLocation")),
        "jd_text": html_to_text(desc),
        "questions": [],
        "error": None,
    }


def parse_greenhouse(url: str) -> dict[str, Any] | None:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path
    qs = urllib.parse.parse_qs(parsed.query)
    board = None
    job_id = None

    m = re.search(r"(?:job-boards|boards)\.greenhouse\.io", host)
    if m:
        m2 = re.search(r"/([^/]+)/jobs/(\d+)", path)
        if m2:
            board, job_id = m2.group(1), m2.group(2)
        if "for" in qs:
            board = qs["for"][0]
        if "token" in qs:
            job_id = qs["token"][0]
    m = re.search(r"^([^.]+)\.greenhouse\.io$", host)
    if m and not board:
        board = m.group(1)
        m2 = re.search(r"/jobs/(\d+)", path)
        if m2:
            job_id = m2.group(1)

    if not board or not job_id:
        return None
    api = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}?content=true&questions=true"
    try:
        final, data = fetch_json(api)
    except (*FETCH_EXCEPTIONS, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    loc = ""
    offices = data.get("offices") or []
    if offices and isinstance(offices, list):
        loc = offices[0].get("name") or ""
    if not loc and isinstance(data.get("location"), dict):
        loc = data["location"].get("name") or ""
    content = data.get("content") or ""
    company = board.replace("-", " ").title() if board else ""
    try:
        _bf, board_info = fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{board}")
        if isinstance(board_info, dict) and board_info.get("name"):
            company = str(board_info["name"]).strip()
    except (*FETCH_EXCEPTIONS, json.JSONDecodeError, ValueError):
        pass
    return {
        "ok": True,
        "url": url,
        "final_url": final,
        "ats": "greenhouse",
        "company": company,
        "role": str(data.get("title") or "").strip(),
        "location": loc,
        "jd_text": html_to_text(str(content)),
        "questions": normalize_greenhouse(data.get("questions")),
        "error": None,
    }


def parse_lever(url: str) -> dict[str, Any] | None:
    m = re.search(r"jobs\.lever\.co/([^/]+)/([^/?#]+)", url)
    if not m:
        return None
    company, job_id = m.group(1), m.group(2)
    if job_id in {"apply", "thanks"}:
        return None
    api = f"https://api.lever.co/v0/postings/{company}/{job_id}"
    try:
        final, data = fetch_json(api)
    except (*FETCH_EXCEPTIONS, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    lists = data.get("lists") or []
    chunks = [html_to_text(str(data.get("description") or ""))]
    for item in lists:
        if not isinstance(item, dict):
            continue
        title = str(item.get("text") or "").strip()
        content = html_to_text(str(item.get("content") or ""))
        if title:
            chunks.append(title)
        if content:
            chunks.append(content)
    extra = html_to_text(str(data.get("additional") or ""))
    if extra:
        chunks.append(extra)
    cats = data.get("categories") or {}
    loc = ""
    if isinstance(cats, dict):
        loc = str(cats.get("location") or "")
    return {
        "ok": True,
        "url": url,
        "final_url": final,
        "ats": "lever",
        "company": str(data.get("company") or company).strip(),
        "role": str(data.get("text") or "").strip(),
        "location": loc,
        "jd_text": "\n\n".join(c for c in chunks if c),
        "questions": harvest_apply_questions(f"https://jobs.lever.co/{company}/{job_id}/apply"),
        "error": None,
    }


def parse_ashby(url: str) -> dict[str, Any] | None:
    m = re.search(r"jobs\.ashbyhq\.com/([^/]+)/([0-9a-fA-F-]{8,})", url)
    if not m:
        return None
    org, job_id = m.group(1), m.group(2)
    api = f"https://api.ashbyhq.com/posting-api/job-board/{urllib.parse.quote(org)}"
    try:
        _final, data = fetch_json(api)
    except (*FETCH_EXCEPTIONS, json.JSONDecodeError, ValueError):
        return None
    jobs = []
    if isinstance(data, dict):
        jobs = data.get("jobs") or data.get("jobPostings") or []
    if not isinstance(jobs, list):
        return None
    match = None
    for job in jobs:
        if not isinstance(job, dict):
            continue
        jid = str(job.get("id") or job.get("jobId") or "")
        jurl = str(job.get("jobUrl") or job.get("applyUrl") or "")
        if jid == job_id or job_id in jurl:
            match = job
            break
    if not match:
        return None
    desc = match.get("descriptionHtml") or match.get("descriptionPlain") or match.get("description") or ""
    loc = ""
    locs = match.get("location") or match.get("locations")
    if isinstance(locs, str):
        loc = locs
    elif isinstance(locs, list) and locs:
        first = locs[0]
        loc = first.get("locationName") if isinstance(first, dict) else str(first)
    elif isinstance(locs, dict):
        loc = str(locs.get("locationName") or locs.get("name") or "")
    return {
        "ok": True,
        "url": url,
        "ats": "ashby",
        "company": str(data.get("organizationName") or org).strip() if isinstance(data, dict) else org,
        "role": str(match.get("title") or "").strip(),
        "location": loc,
        "jd_text": html_to_text(str(desc)),
        "questions": harvest_apply_questions(url),
        "error": None,
    }


def _walk_find(obj: Any, keys: set[str]) -> dict[str, Any] | None:
    if isinstance(obj, dict):
        if keys <= set(obj) or (len(keys) == 1 and keys & set(obj)):
            if "jobsData" in obj and isinstance(obj.get("jobsData"), dict):
                return obj
            if keys <= set(obj):
                return obj
        for v in obj.values():
            found = _walk_find(v, keys)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _walk_find(v, keys)
            if found is not None:
                return found
    return None


def parse_apple(url: str) -> dict[str, Any] | None:
    if "jobs.apple.com" not in url.lower():
        return None
    try:
        _final, html = fetch_text(url, accept="text/html")
    except FETCH_EXCEPTIONS:
        return None
    m = re.search(
        r'window\.__staticRouterHydrationData\s*=\s*JSON\.parse\("((?:\\.|[^"\\])*)"\)',
        html,
    )
    if not m:
        return None
    try:
        data = json.loads(json.loads('"' + m.group(1) + '"'))
    except json.JSONDecodeError:
        return None
    blob = _walk_find(data, {"jobsData"})
    job = blob.get("jobsData") if blob and isinstance(blob.get("jobsData"), dict) else None
    if job is None:
        job = _walk_find(data, {"postingTitle", "jobSummary"})
    if not isinstance(job, dict):
        return None
    locs = job.get("locations") or []
    loc_parts = []
    if isinstance(locs, list):
        for item in locs:
            if isinstance(item, dict):
                loc_parts.append(str(item.get("name") or item.get("countryName") or ""))
            else:
                loc_parts.append(str(item))
    parts = []
    summary = html_to_text(str(job.get("jobSummary") or ""))
    desc = html_to_text(str(job.get("description") or ""))
    if summary:
        parts.append(summary)
    if desc and desc not in summary:
        parts.append(desc)
    minq = html_to_text(str(job.get("minimumQualifications") or ""))
    pref = html_to_text(str(job.get("preferredQualifications") or ""))
    if minq:
        parts.append("Minimum Qualifications\n" + minq)
    if pref:
        parts.append("Preferred Qualifications\n" + pref)
    jd = "\n\n".join(p for p in parts if p.strip())
    role = str(job.get("postingTitle") or job.get("title") or "").strip()
    if len(jd) < 80:
        return None
    return {
        "ok": True,
        "url": url,
        "ats": "apple",
        "company": "Apple",
        "role": role,
        "location": ", ".join(p for p in loc_parts if p),
        "jd_text": jd,
        "questions": apple_questions(job) or extract_questions_from_html(html),
        "error": None,
    }


def parse_workday(url: str) -> dict[str, Any] | None:
    m = re.search(
        r"https?://([^.]+)\.wd\d+\.myworkdayjobs\.com/([^/]+)/.*/([A-Z0-9][-A-Z0-9]+)",
        url,
        re.I,
    )
    if not m:
        return None
    tenant, site, job_id = m.group(1), m.group(2), m.group(3)
    api = f"https://{tenant}.wd1.myworkdayjobs.com/wday/cxs/{tenant}/{site}/job/{job_id}"
    # Host in the original URL may be wd5 etc; reuse the original netloc.
    parsed = urllib.parse.urlparse(url)
    api = f"{parsed.scheme}://{parsed.netloc}/wday/cxs/{tenant}/{site}/job/{job_id}"
    try:
        _final, data = fetch_json(api)
    except (*FETCH_EXCEPTIONS, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    info = data.get("jobPostingInfo") or data
    if not isinstance(info, dict):
        return None
    desc = info.get("jobDescription") or info.get("jobDescriptionText") or ""
    return {
        "ok": True,
        "url": url,
        "ats": "workday",
        "company": tenant.replace("_", " ").title(),
        "role": str(info.get("title") or data.get("title") or "").strip(),
        "location": str(info.get("location") or ""),
        "jd_text": html_to_text(str(desc)),
        "questions": workday_questions(info) or harvest_apply_questions(url),
        "error": None,
    }


HEADLINE_SEPS = (" :: ", " | ", " – ", " — ", " - ")
ROLE_HINT = re.compile(
    r"software|\bswe\b|engineer|scientist|developer|\binterns?\b|machine learning|"
    r"\bml\b|\bai\b|data scien|research engineer|programmer|\bsre\b|devops|"
    r"backend|front[- ]?end|full[- ]?stack|applied scientist|data engineer",
    re.I,
)
PROGRAM_HINT = re.compile(
    r"internship program|summer internship program|campus undergraduate|"
    r"early career program|university (?:recruit|program)|student program|"
    r"undergraduate summer internship",
    re.I,
)
LOCATION_HINT = re.compile(
    r"(?i)^(united states|usa|u\.s\.a?\.?|uk|united kingdom|canada|remote|"
    r"hybrid|worldwide|global)$"
)
CITY_ST = re.compile(r"^[A-Za-z .'-]+,\s*[A-Z]{2}$")
COMPANY_HINT = re.compile(
    r"\b(inc|llc|ltd|corp|corporation|technologies|labs|company)\.?$",
    re.I,
)
ORACLE_JOB = re.compile(
    r"https?://([^/]*oraclecloud\.com)/hcmUI/CandidateExperience/[^/]+"
    r"/sites/([^/]+)/job/([^/?#]+)",
    re.I,
)


def headline_kind(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return "empty"
    if LOCATION_HINT.match(t) or (CITY_ST.match(t) and not ROLE_HINT.search(t)):
        return "location"
    role = bool(ROLE_HINT.search(t))
    program = bool(PROGRAM_HINT.search(t))
    if program and not role:
        return "program"
    if role:
        return "role"
    if COMPANY_HINT.search(t) or (len(t.split()) <= 3 and len(t) <= 40):
        return "company"
    return "unknown"


def split_headline(headline: str, site: str = "") -> tuple[str, str]:
    """Return (role, company). Do not treat a campus program name as the role."""
    headline = (headline or "").strip()
    site = (site or "").strip()
    if not headline:
        return "", site

    left = right = ""
    for sep in HEADLINE_SEPS:
        if sep in headline:
            left, right = (p.strip() for p in headline.rsplit(sep, 1))
            break
    if not right:
        return headline, site

    lk, rk = headline_kind(left), headline_kind(right)
    if rk == "location" and lk != "location":
        return left, site
    if lk == "location" and rk != "location":
        return right, site
    if lk == "program" and rk == "role":
        return right, site
    if rk == "program" and lk == "role":
        return left, site
    if rk == "role" and lk in {"company", "unknown", "program"}:
        return right, site or left
    if lk == "role":
        company = right if rk in {"company", "unknown"} and not site else (site or right)
        return left, company
    return left, right or site


def company_from_boilerplate(html: str) -> str:
    text = html_to_text(html or "")
    if not text:
        return ""
    m = re.search(r"\bAt\s+([A-Z][\w&.’' -]{1,50}?),", text)
    if m:
        name = re.sub(r"\s+", " ", m.group(1)).strip(" -")
        if 2 <= len(name) <= 60:
            return name
    m = re.match(r"([A-Z][\w&.’'-]*(?:[\s][A-Z][\w&.’'-]*){0,5}),", text)
    if m:
        name = m.group(1).strip()
        if name.lower() not in {"the", "our", "this", "a"} and 2 <= len(name) <= 60:
            return name
    return ""


def _oracle_headers() -> dict[str, str]:
    return {
        "ora-irc-cx-userid": str(uuid.uuid4()),
        "ora-irc-language": "en",
        "Content-Type": "application/vnd.oracle.adf.resourceitem+json;charset=utf-8",
    }


def parse_oracle(url: str) -> dict[str, Any] | None:
    m = ORACLE_JOB.search(url)
    if not m:
        return None
    host, site, job_id = m.group(1), m.group(2), m.group(3)
    # Finder separators must stay literal; do not urlencode.
    api = (
        f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
        f'?expand=all&onlyData=true&finder=ById;Id="{job_id}",siteNumber={site}'
    )
    try:
        _final, data = fetch_json(api, headers=_oracle_headers())
    except (*FETCH_EXCEPTIONS, json.JSONDecodeError, ValueError, urllib.error.HTTPError):
        return None
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        return None
    job = items[0]
    chunks = []
    for key in (
        "ExternalDescriptionStr",
        "ExternalResponsibilitiesStr",
        "ExternalQualificationsStr",
    ):
        chunk = html_to_text(str(job.get(key) or ""))
        if chunk:
            chunks.append(chunk)
    flex = job.get("requisitionFlexFields") or []
    if isinstance(flex, list):
        extra = []
        for field in flex:
            if not isinstance(field, dict):
                continue
            prompt = str(field.get("Prompt") or "").strip()
            value = str(field.get("Value") or "").strip()
            if prompt and value:
                extra.append(f"{prompt}: {value}")
        if extra:
            chunks.append("\n".join(extra))
    jd = "\n\n".join(chunks)
    if len(jd) < 80:
        return None
    company = company_from_boilerplate(str(job.get("CorporateDescriptionStr") or ""))
    title = str(job.get("Title") or job.get("OtherRequisitionTitle") or "").strip()
    role, company = split_headline(title, company)
    loc = str(job.get("PrimaryLocation") or "").strip()
    workplace = str(job.get("WorkplaceType") or "").strip()
    if workplace and workplace.lower() not in loc.lower():
        loc = f"{loc} ({workplace})" if loc else workplace
    return {
        "ok": True,
        "url": url,
        "ats": "oracle",
        "company": company,
        "role": role or title,
        "location": loc,
        "jd_text": jd,
        "questions": [],
        "error": None,
    }


def parse_html(url: str) -> dict[str, Any]:
    try:
        final, html = fetch_text(url, accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
    except urllib.error.HTTPError as e:
        return fail(url, f"http {e.code}")
    except FETCH_EXCEPTIONS as e:
        return fail(url, f"{type(e).__name__}: {e}")

    jobs = extract_json_ld_jobs(html)
    if jobs:
        out = from_jobposting(jobs[0], url)
        out["final_url"] = final
        out["questions"] = extract_questions_from_html(html)
        if len(out.get("jd_text") or "") >= MIN_JD_CHARS:
            return out

    title = ""
    tm = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    if tm:
        title = html_to_text(tm.group(1))

    og = ""
    om = re.search(
        r'(?is)<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
        html,
    )
    if om:
        og = htmlmod.unescape(om.group(1)).strip()

    site = ""
    sm = re.search(
        r'(?is)<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)',
        html,
    )
    if sm:
        site = htmlmod.unescape(sm.group(1)).strip()

    main = html
    for sel in (
        r'(?is)<main\b[^>]*>(.*?)</main>',
        r'(?is)<article\b[^>]*>(.*?)</article>',
        r'(?is)<div[^>]+(?:id|class)=["\'][^"\']*(?:job[-_ ]?(?:description|details|posting)|posting|description)[^"\']*["\'][^>]*>(.*?)</div>',
    ):
        mm = re.search(sel, html)
        if mm and len(mm.group(1)) > 400:
            main = mm.group(1)
            break

    text = strip_tags(main)
    # Drop obvious chrome
    for noise in (
        r"(?im)^.*(cookie|sign in|log in|privacy policy|terms of use).*$",
    ):
        text = re.sub(noise, "", text)

    headline = og or title
    role, company = split_headline(headline, site)

    return {
        "ok": len(text) >= MIN_JD_CHARS,
        "url": url,
        "final_url": final,
        "ats": "html",
        "company": company,
        "role": role,
        "location": "",
        "jd_text": text,
        "questions": extract_questions_from_html(html),
        "error": None if len(text) >= MIN_JD_CHARS else "too_short",
    }


def fail(url: str, error: str) -> dict[str, Any]:
    return {
        "ok": False,
        "url": url,
        "ats": "unknown",
        "company": "",
        "role": "",
        "location": "",
        "jd_text": "",
        "questions": [],
        "error": error,
    }


def harvest_apply_questions(url: str, html: str | None = None) -> list[dict[str, Any]]:
    """Pull apply-form fields from the posting, then follow Start Application / Apply links."""
    if not url and not html:
        return []
    page = html or ""
    if not page and url:
        try:
            _final, page = fetch_text(url, accept="text/html")
        except (*FETCH_EXCEPTIONS, ValueError):
            return []
    questions = extract_questions_from_html(page)
    if questions_look_real(questions):
        return questions
    extra: list[dict[str, Any]] = []
    for href in find_apply_hrefs(page, url):
        try:
            _final, apply_html = fetch_text(href, accept="text/html")
        except (*FETCH_EXCEPTIONS, ValueError):
            continue
        extra = merge_questions(extra, extract_questions_from_html(apply_html))
        if questions_look_real(extra):
            break
    return merge_questions(questions, extra)


def apple_questions(job: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            prompt = obj.get("questionText") or obj.get("question") or obj.get("prompt") or obj.get("name")
            qtype = str(obj.get("questionType") or obj.get("type") or "")
            if prompt and isinstance(prompt, str) and len(prompt) > 8:
                if qtype.lower() in {"applicationquestion", "rolespecificquestion"}:
                    pass
                key = prompt.strip().lower()
                if key not in seen and not re.match(r"^(jobsite\.|posting)", prompt):
                    seen.add(key)
                    kind = "written" if "text" in qtype.lower() else "other"
                    out.append(
                        {
                            "prompt": prompt.strip(),
                            "required": bool(obj.get("required") or obj.get("isRequired")),
                            "type": qtype or "unknown",
                            "options": [
                                str(x.get("label") or x)
                                for x in (obj.get("choices") or obj.get("options") or [])
                                if x
                            ],
                            "name": str(obj.get("id") or ""),
                            "description": "",
                            "kind": kind,
                        }
                    )
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(job.get("questionCategories") or job)
    return out[:80]


def workday_questions(info: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    blobs = [
        info.get("questionnaire"),
        info.get("jobPostingQuestionnaire"),
        info.get("screeningQuestionnaire"),
        info.get("questions"),
    ]
    for blob in blobs:
        if not blob:
            continue
        items = blob if isinstance(blob, list) else blob.get("questions") or blob.get("items") or []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            prompt = str(item.get("question") or item.get("text") or item.get("label") or "").strip()
            if not prompt:
                continue
            out.append(
                {
                    "prompt": prompt,
                    "required": bool(item.get("required") or item.get("isRequired")),
                    "type": str(item.get("type") or "unknown"),
                    "options": [
                        str(x.get("label") or x)
                        for x in (item.get("answerChoices") or item.get("choices") or [])
                        if x
                    ],
                    "name": str(item.get("id") or ""),
                    "description": "",
                    "kind": "screening",
                }
            )
    return out


def scrape_one(url: str, browser: bool = False) -> dict[str, Any]:
    try:
        result = _scrape_one(url)
    except Exception as e:
        result = fail(url, f"{type(e).__name__}: {e}")
    if browser and not questions_look_real(result.get("questions")):
        try:
            from harvest_apply_form import harvest_apply_form

            harvested = harvest_apply_form(url)
            extra = harvested.get("questions") or []
            if extra:
                result["questions"] = merge_questions(result.get("questions") or [], extra)
            result["apply_clicked"] = harvested.get("clicked")
            result["login_walled"] = harvested.get("login_walled")
            if harvested.get("error") and not questions_look_real(result.get("questions")):
                result["question_error"] = harvested["error"]
        except Exception as e:
            result["question_error"] = f"{type(e).__name__}: {e}"
    return result


def _scrape_one(url: str) -> dict[str, Any]:
    url = url.strip()
    if not re.match(r"^https?://", url, re.I):
        return fail(url, "not_http_url")

    parsers = []
    host = urllib.parse.urlparse(url).netloc.lower()
    if "greenhouse.io" in host:
        parsers.append(parse_greenhouse)
    if "lever.co" in host:
        parsers.append(parse_lever)
    if "ashbyhq.com" in host:
        parsers.append(parse_ashby)
    if "jobs.apple.com" in host:
        parsers.append(parse_apple)
    if "myworkdayjobs.com" in host:
        parsers.append(parse_workday)
    if "oraclecloud.com" in host:
        parsers.append(parse_oracle)

    last_err = None
    for parser in parsers:
        try:
            result = parser(url)
        except Exception as e:
            result = None
            last_err = str(e)
        if result and result.get("ok") and len(result.get("jd_text") or "") >= MIN_JD_CHARS:
            if not questions_look_real(result.get("questions")):
                result["questions"] = harvest_apply_questions(url)
            return result
        if result and result.get("ok") and result.get("role") and len(result.get("jd_text") or "") >= 80:
            if not questions_look_real(result.get("questions")):
                result["questions"] = harvest_apply_questions(url)
            return result
        if result and result.get("error"):
            last_err = str(result["error"])

    try:
        html_result = parse_html(url)
    except Exception as e:
        return fail(url, last_err or f"{type(e).__name__}: {e}")
    if parsers and not html_result.get("ok") and last_err:
        html_result["error"] = html_result.get("error") or last_err
    if html_result.get("ok") and not questions_look_real(html_result.get("questions")):
        html_result["questions"] = harvest_apply_questions(url) or html_result.get("questions")
    return html_result


def main(argv: list[str]) -> int:
    browser = "--browser" in argv
    urls = [a for a in argv[1:] if a.strip() and not a.startswith("-")]
    if not urls:
        print("usage: scrape_jd.py [--browser] URL [URL...]", file=sys.stderr)
        return 2
    results = [scrape_one(u, browser=browser) for u in urls]
    if len(results) == 1:
        json.dump(results[0], sys.stdout, ensure_ascii=False, indent=2)
    else:
        json.dump(results, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
