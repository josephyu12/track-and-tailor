"""Drop postings whose offices are all outside the United States.

A US office, or a location we cannot place (Remote, a bare city), keeps the
job. Canada, the UK, and other countries are skipped only when none of the
locations are in the US.
"""

from __future__ import annotations

import re
from typing import Iterable

US_ABBR = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}
CA_PROVINCES = {
    "AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT",
}
_US_NAME = (
    r"alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|"
    r"district of columbia|florida|georgia|hawaii|idaho|illinois|indiana|iowa|"
    r"kansas|kentucky|louisiana|maine|maryland|massachusetts|michigan|minnesota|"
    r"mississippi|missouri|montana|nebraska|nevada|new hampshire|new jersey|"
    r"new mexico|new york|north carolina|north dakota|ohio|oklahoma|oregon|"
    r"pennsylvania|puerto rico|rhode island|south carolina|south dakota|"
    r"tennessee|texas|utah|vermont|virginia|washington|west virginia|wisconsin|"
    r"wyoming|virgin islands"
)
_FOREIGN = (
    r"canada|united kingdom|england|scotland|wales|northern ireland|ireland|"
    r"germany|france|india|spain|australia|united arab emirates|dubai|europe|"
    r"south america|singapore|netherlands|brazil|israel|switzerland|sweden|"
    r"japan|china|korea|hong kong|taiwan|mexico|new zealand|ontario|"
    r"british columbia|québec|quebec|alberta|manitoba|saskatchewan|"
    r"nova scotia|new brunswick|newfoundland|prince edward island|yukon"
)
_US_RE = re.compile(
    rf"\b(?:united states|usa|{_US_NAME})\b|u\.s\.a?\.?",
    re.I,
)
_FOREIGN_RE = re.compile(rf"\b(?:{_FOREIGN})\b|\buk\b|\bu\.k\.\b|\buae\b", re.I)
_GENERIC = {
    "remote",
    "hybrid",
    "multiple",
    "multiple locations",
    "various",
    "various locations",
    "several locations",
}
_NICK = {"nyc", "sf", "south sf", "manhattan", "bay area"}


def location_kind(loc: str) -> str:
    """'us', 'foreign', or 'unknown'."""
    raw = str(loc or "").strip()
    low = re.sub(r"\s+", " ", raw.lower())
    if not low:
        return "unknown"
    if low in _NICK or "remote in us" in low or _US_RE.search(low):
        return "us"
    last = re.split(r"[\s,]+", raw)[-1].strip(".").upper()
    parts = [p.strip(" .") for p in re.split(r"[,/|]", raw) if p.strip()]
    if last in US_ABBR or last in {"NYC", "SF"} or any(p.upper() in US_ABBR for p in parts):
        return "us"
    if (
        _FOREIGN_RE.search(low)
        or last in CA_PROVINCES
        or last in {"UK", "CAN", "UAE"}
        or any(p.upper() in CA_PROVINCES for p in parts)
    ):
        return "foreign"
    if low in _GENERIC:
        return "unknown"
    return "unknown"


def outside_us(locations: Iterable[str]) -> bool:
    """True when every listed place is outside the US."""
    labels = [str(x).strip() for x in locations if str(x).strip()]
    if not labels:
        return False
    kinds = [location_kind(x) for x in labels]
    if any(k != "foreign" for k in kinds):
        return False
    return True


def posting_outside_us(listing_locations: Iterable[str], scraped_location: str = "") -> bool:
    """Skip when the posting is abroad and no location is in the US.

    A scraped city wins over a generic board label such as Remote.
    A US office on the listing keeps a multi-site posting.
    """
    places = [str(x).strip() for x in listing_locations if str(x).strip()]
    scraped = str(scraped_location or "").strip()
    if any(location_kind(x) == "us" for x in places):
        return False
    if scraped and location_kind(scraped) == "us":
        return False
    if scraped and location_kind(scraped) == "foreign":
        return True
    return outside_us(places)
