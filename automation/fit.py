#!/usr/bin/env python3
"""Skip internship listings that are not a real SWE / ML / data fit.

Default skill list is a generic SWE/ML intern stack. Edit SKILLS or
automation/config.json if your background is different. Trading, hardware,
product, and specialized robotics/SLAM/lidar roles are skipped by default.
CNN / spectrogram computer vision is in-scope.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Keep aligned with master/resume.tex skills + experience.
SKILLS = (
    "python", "javascript", "typescript", "java", "c++", "rust", "sql", "swift",
    "react", "node", "dagster", "kubernetes", "flask", "fastapi", "graphql",
    "postgres", "pytorch", "tensorflow", "aws", "eks", "ec2", "s3", "lambda",
    "docker", "gitlab", "datadog", "redis", "oracle", "jupyter", "huggingface",
    "machine learning", "deep learning", "llm", "backend", "full-stack", "fullstack",
    "data structures", "algorithms", "distributed", "api", "microservices",
    "cloud", "gpu", "pytorch", "scikit",
    "cnn", "keras", "computer vision", "signal processing",
)

TITLE_SWE = re.compile(
    r"software|swe\b|backend|front[- ]?end|full[- ]?stack|site reliability|\bsre\b|"
    r"devops|platform engineer|infrastructure|mlops|data engineer|machine learning|"
    r"\bml engineer|\bai engineer|research engineer|applied scientist|"
    r"computational|bioinformatics|cheminformatics|security engineer|"
    r"systems programmer|developer intern|software development",
    re.I,
)
TITLE_ML_DATA = re.compile(
    r"machine learning|\bml\b|\bai\b|data science|data scientist|data engineer|"
    r"analytics|modeling program|quantitative developer|quant developer|"
    r"quant research engineer|research scientist",
    re.I,
)
TITLE_SKIP = re.compile(
    r"trading analyst|\btrader\b|portfolio manager|investment banking|private equity|"
    r"sales intern|marketing intern|product manager|\bpm intern\b|recruiter|"
    r"human resources|\bhr intern\b|accountant|audit intern|\btax intern\b|"
    r"mechanical engineer|electrical engineer|civil engineer|chemical engineer|"
    r"materials engineer|hardware intern|analog|pcb\b|\bfpga\b|asic\b|"
    r"supply chain|graphic design|\bux intern\b|\bui intern\b|industrial design|"
    r"quant trader|prop trad|equity research analyst|credit analyst|"
    r"business analyst intern|consulting intern|operations intern|"
    r"firmware intern|embedded hardware",
    re.I,
)
DOMAIN_PENALTY = re.compile(
    r"\bperception\b|\bcv intern\b|\brobotics\b|\bslam\b|"
    r"\blidar\b|\bdrone\b|autonomous vehicle|tensorrt|controls intern|"
    r"embedded firmware|rf engineer|antenna|solidworks|\bcad\b|"
    r"fixed income|trade floor|sell-side|portfolio management|"
    r"bloomberg|cfa\b|pitch book|financial modeling",
    re.I,
)
SENIOR_ONLY = re.compile(
    r"\bph\.?d\b required|masters? required|master'?s only|"
    r"\b[3-9]\+ years|\b5\+ years of experience",
    re.I,
)
JD_SWE_ML = re.compile(
    r"software engineer|write code|python|java\b|c\+\+|machine learning|"
    r"backend|api\b|distributed|kubernetes|aws|pytorch|tensorflow|"
    r"data engineer|full[- ]?stack",
    re.I,
)

DEFAULT_MIN_SCORE = 0.40


@dataclass
class Fit:
    ok: bool
    score: float
    reason: str


def _blob(title: str, jd: str, category: str, company: str = "") -> str:
    return f"{title}\n{company}\n{category}\n{jd}"[:12000]


def title_for_fit(title: str, company: str = "") -> str:
    """Score role and company together so a swapped HTML title still matches."""
    return f"{title or ''} {company or ''}".strip()


def skill_hits(text: str) -> list[str]:
    low = text.lower()
    hits = []
    for sk in SKILLS:
        if sk in low and sk not in hits:
            hits.append(sk)
    return hits


def evaluate_fit(
    title: str,
    jd: str = "",
    category: str = "",
    min_score: float = DEFAULT_MIN_SCORE,
    company: str = "",
) -> Fit:
    title = title or ""
    jd = jd or ""
    category = category or ""
    company = company or ""
    title_text = title_for_fit(title, company)
    text = _blob(title, jd, category, company)

    if TITLE_SKIP.search(title) or (not title.strip() and TITLE_SKIP.search(company)):
        return Fit(False, 0.0, f"title is not a SWE/ML/data role ({title.strip() or company.strip()})")
    if SENIOR_ONLY.search(text) and not TITLE_SWE.search(title_text):
        return Fit(False, 0.05, "listing looks advanced-degree or senior-only")

    score = 0.0
    reasons: list[str] = []

    if TITLE_SWE.search(title_text):
        score += 0.42
        reasons.append("software/ML title")
    elif TITLE_ML_DATA.search(title_text):
        score += 0.34
        reasons.append("data/ML title")
    elif re.search(r"\bengineer intern|\bengineering intern|\bdeveloper\b", title_text, re.I):
        score += 0.22
        reasons.append("generic engineer intern title")
    else:
        score += 0.05
        reasons.append("title is not SWE/ML/data")

    hits = skill_hits(text)
    skill_pts = min(0.36, 0.045 * len(hits))
    score += skill_pts
    if hits:
        reasons.append(f"{len(hits)} resume skills in JD")

    if jd and JD_SWE_ML.search(jd):
        score += 0.10
    elif jd and TITLE_SWE.search(title_text):
        score += 0.04

    penalties = DOMAIN_PENALTY.findall(text)
    if penalties:
        # Specialized robotics/SLAM/lidar/trading language vs the user's actual work.
        uniq = {p.lower() for p in penalties}
        penalty = min(0.28, 0.08 * len(uniq))
        score -= penalty
        reasons.append("domain mismatch: " + ", ".join(sorted(uniq)[:4]))

    if not TITLE_SWE.search(title_text) and not TITLE_ML_DATA.search(title_text):
        score -= 0.12

    score = max(0.0, min(1.0, score))
    ok = score + 1e-9 >= min_score
    reason = "; ".join(reasons) + f" (score {score:.2f}, need {min_score:.2f})"
    if not ok:
        reason = "not a strong fit — " + reason
    return Fit(ok, round(score, 3), reason)


def evaluate_listing(
    listing: dict[str, Any],
    jd: str = "",
    min_score: float = DEFAULT_MIN_SCORE,
) -> Fit:
    return evaluate_fit(
        title=str(listing.get("title") or ""),
        jd=jd,
        category=str(listing.get("category") or ""),
        min_score=min_score,
        company=str(listing.get("company_name") or listing.get("company") or ""),
    )


def write_fit_json(folder: Path, fit: Fit, extra: dict[str, Any] | None = None) -> Path:
    """Sidecar the dashboard reads. Scoring itself is local regex, not an LLM call."""
    folder.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"ok": fit.ok, "score": fit.score, "reason": fit.reason}
    if extra:
        payload.update(extra)
    path = folder / "fit.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def sync_fit_json(folder: Path, min_score: float = DEFAULT_MIN_SCORE) -> bool:
    """Rescore from job.md. Overwrites a stale fit.json. Preserves extra keys."""
    job = folder / "job.md"
    if not job.is_file():
        return False
    fit = evaluate_job_md(job.read_text(encoding="utf-8", errors="replace"), min_score)
    extra: dict[str, Any] = {}
    path = folder / "fit.json"
    if path.is_file():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            old = {}
        if isinstance(old, dict):
            extra = {k: v for k, v in old.items() if k not in {"ok", "score", "reason"}}
            if (
                old.get("ok") == fit.ok
                and old.get("score") == fit.score
                and old.get("reason") == fit.reason
            ):
                return False
    write_fit_json(folder, fit, extra=extra or None)
    return True


def fields_from_job_md(text: str) -> dict[str, str]:
    company, role, category = "", "", ""
    jd_lines: list[str] = []
    in_jd = False
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            if " — " in title:
                company, role = title.split(" — ", 1)
            else:
                company = title
        elif line.startswith("- ") and ":" in line:
            key, val = line[2:].split(":", 1)
            if key.strip().lower() == "category":
                category = val.strip()
        elif line.strip() == "## Job description":
            in_jd = True
        elif in_jd and line.startswith("## "):
            break
        elif in_jd:
            jd_lines.append(line)
    return {
        "company": company,
        "role": role,
        "category": category,
        "jd": "\n".join(jd_lines).strip(),
    }


def evaluate_job_md(text: str, min_score: float = DEFAULT_MIN_SCORE) -> Fit:
    fields = fields_from_job_md(text)
    return evaluate_fit(
        fields["role"],
        fields["jd"],
        fields["category"],
        min_score=min_score,
        company=fields["company"],
    )


def backfill_missing_fits(
    apps: Path,
    min_score: float = DEFAULT_MIN_SCORE,
) -> int:
    """Write or refresh fit.json from each folder's job.md."""
    if not apps.is_dir():
        return 0
    wrote = 0
    for folder in sorted(apps.iterdir()):
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        if sync_fit_json(folder, min_score):
            wrote += 1
    return wrote
