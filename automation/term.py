#!/usr/bin/env python3
"""Keep only internships that include Summer 2027 (May/June–Aug/Sep).

Skip when the posting is offered only at some other time. Multiple windows
are fine as long as Summer 2027 is one of them. No dates → do not skip.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

CORE_START = 2027 * 12 + 6  # June 2027
CORE_END = 2027 * 12 + 8  # August 2027
SUMMER_START_MONTHS = {5, 6, 7}

MONTH_NUM = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}
MONTH_NAME = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}

SEASON_YEAR = re.compile(
    r"\b(summer|fall|autumn|winter|spring)\s*(?:of\s+)?(?:20)?(\d{2})\b",
    re.I,
)
MONTH = (
    r"(?:january|february|march|april|may|june|july|august|september|"
    r"october|november|december|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec)\.?"
)
RANGE = re.compile(
    rf"({MONTH})\s*(?:\d{{1,2}}(?:st|nd|rd|th)?,?\s*)?(20\d{{2}})?"
    rf"\s*(?:[-–—/]|to|through|thru|\s+until\s+)\s*"
    rf"({MONTH})\s*(?:\d{{1,2}}(?:st|nd|rd|th)?,?\s*)?(20\d{{2}})?",
    re.I,
)
START_MONTH_YEAR = re.compile(
    rf"(?:start(?:s|ing)?(?:\s+date)?|begin(?:s|ning)?)\s*:?\s*"
    rf"({MONTH})\s*(?:\d{{1,2}}(?:st|nd|rd|th)?,?\s*)?(20\d{{2}})",
    re.I,
)
MONTH_YEAR = re.compile(
    rf"({MONTH})\s+(?:(?:\d{{1,2}}(?:st|nd|rd|th)?,?\s+)?)(20\d{{2}})",
    re.I,
)
DEADLINE_LINE = re.compile(
    r"(apply by|application deadline|applications? (?:close|due)|posted on|date posted)[^\n.]{0,60}",
    re.I,
)
GRAD_LINE = re.compile(
    r"(?:expected |anticipated )?(?:graduat(?:e|ing|ion)(?:\s+date)?|class of(?:\s+20\d{2})?|"
    r"enrolled (?:full[- ]time )?(?:in|through|until)|must be (?:a )?(?:rising )?"
    r"(?:freshman|sophomore|junior|senior))[^\n.]{0,90}",
    re.I,
)


@dataclass
class Term:
    ok: bool
    reason: str
    summer_2027: bool = False
    other: list[str] = field(default_factory=list)


def _year(raw: str | None) -> int | None:
    if not raw:
        return None
    y = int(raw)
    if y < 100:
        y += 2000
    return y


def _month(raw: str) -> int:
    return MONTH_NUM[raw.strip(".").lower()]


def _ord(month: int, year: int) -> int:
    return year * 12 + month


def _clean(text: str) -> str:
    return GRAD_LINE.sub(" ", DEADLINE_LINE.sub(" ", text or ""))


def _label(season: str, year: int) -> str:
    return f"{season.capitalize()} {year}"


def _overlaps_summer_2027(m1: int, y1: int, m2: int, y2: int) -> bool:
    start, end = _ord(m1, y1), _ord(m2, y2)
    if end < start:
        start, end = end, start
    return start <= CORE_END and end >= CORE_START


def _parse_named(blob: str) -> tuple[bool, list[str]]:
    summer_2027 = False
    other: list[str] = []
    for m in SEASON_YEAR.finditer(blob):
        season = m.group(1).lower()
        if season == "autumn":
            season = "fall"
        year = _year(m.group(2))
        if year is None:
            continue
        if season == "summer" and year == 2027:
            summer_2027 = True
        else:
            lab = _label(season, year)
            if lab not in other:
                other.append(lab)
    return summer_2027, other


def _add_other(other: list[str], lab: str) -> None:
    if lab and lab not in other:
        other.append(lab)


def _parse_ranges(blob: str) -> tuple[bool, list[str]]:
    summer_2027 = False
    other: list[str] = []
    for m in RANGE.finditer(blob):
        y2 = _year(m.group(4))
        y1 = _year(m.group(2)) or y2
        y2 = y2 or y1
        if not y1 or not y2:
            continue
        m1, m2 = _month(m.group(1)), _month(m.group(3))
        lab = f"{MONTH_NAME[m1]} {y1}-{MONTH_NAME[m2]} {y2}"
        if _overlaps_summer_2027(m1, y1, m2, y2):
            summer_2027 = True
        else:
            _add_other(other, lab)
    for m in START_MONTH_YEAR.finditer(blob):
        month, year = _month(m.group(1)), _year(m.group(2))
        if not year:
            continue
        if year == 2027 and month in SUMMER_START_MONTHS:
            summer_2027 = True
        else:
            _add_other(other, f"starts {m.group(1).title()} {year}")
    if not summer_2027:
        for m in MONTH_YEAR.finditer(blob):
            month, year = _month(m.group(1)), _year(m.group(2))
            if year == 2027 and month in SUMMER_START_MONTHS | {8}:
                summer_2027 = True
                break
    return summer_2027, other


def _bare_summer_undated(blob: str, has_other: bool) -> bool:
    if has_other or SEASON_YEAR.search(blob):
        return False
    return bool(re.search(r"\bsummer\b", blob, re.I))


def parse_timing(title: str = "", jd: str = "", terms: Iterable[str] | None = None) -> tuple[bool, list[str]]:
    parts = [title or "", " ".join(str(t) for t in (terms or [])), jd or ""]
    blob = _clean("\n".join(parts))
    s1, o1 = _parse_named(blob)
    s2, o2 = _parse_ranges(blob)
    summer = s1 or s2
    other: list[str] = []
    for lab in o1 + o2:
        _add_other(other, lab)
    if not summer and _bare_summer_undated(blob, bool(other)):
        summer = True
    return summer, other


def evaluate_term(
    title: str = "",
    jd: str = "",
    terms: Iterable[str] | None = None,
) -> Term:
    """Skip only when the posting itself is exclusively a non-summer-2027 window."""
    terms = list(terms or [])
    posting_summer, posting_other = parse_timing(title, jd, terms=())
    listed_summer, listed_other = parse_timing("", "", terms=terms)

    if posting_summer:
        extra = f"; also {', '.join(posting_other[:3])}" if posting_other else ""
        return Term(True, f"offers Summer 2027 (May/June-Aug/Sep){extra}", True, posting_other)
    if posting_other:
        return Term(
            False,
            "only offered " + ", ".join(posting_other[:4]) + " - not Summer 2027 (May/June-Aug/Sep)",
            False,
            posting_other,
        )
    if listed_summer:
        return Term(True, "listing tagged Summer 2027", True, listed_other)
    if listed_other:
        return Term(
            False,
            "only offered " + ", ".join(listed_other[:4]) + " - not Summer 2027 (May/June-Aug/Sep)",
            False,
            listed_other,
        )
    return Term(True, "no other-term dates; treating as eligible", False, [])


def evaluate_listing_term(listing: dict[str, Any], jd: str = "") -> Term:
    return evaluate_term(
        title=str(listing.get("title") or ""),
        jd=jd,
        terms=listing.get("terms") or [],
    )


def custom_term_alert(term: Term) -> str:
    return (
        f"Not a Summer 2027 internship (May/June-Aug/Sep). {term.reason} "
        "Not continuing."
    )
