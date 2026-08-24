# Track and Tailor

Watch new internship listings, then tailor a one-page LaTeX resume to each one.

The pipeline diffs [SimplifyJobs internship listings](https://github.com/SimplifyJobs/Summer2027-Internships), scores fit, scrapes the posting, and runs the Cursor Agent CLI against your master resume.

This is a personal tool you run on your machine. It is not a hosted product. Tailoring uses your Cursor login. The listing feed is Simplify's public JSON.

## Setup

```bash
cp master/resume.example.tex master/resume.tex
cp master/bank.example.md master/bank.md
cp .cursor/skills/tailor-resume/profile.example.json .cursor/skills/tailor-resume/profile.json
# edit those three files so they are about you
agent login
make internships-install
make internships-dashboard
```

`master/resume.tex`, `master/bank.md`, `profile.json`, and `applications/` stay gitignored so a public fork does not publish your resume or form answers.

## Commands

| Make target | What it does |
|---|---|
| `internships-install` | launchd at the configured hour + dashboard on `127.0.0.1:8765` |
| `internships-now` | run once |
| `internships-dry` | fetch + diff only |
| `internships-report` | rebuild today's HTML report |
| `internships-gc` | prune old application folders / logs |
| `internships-dashboard` | open the local UI |
| `internships-uninstall` | remove launchd jobs |

Config lives in `automation/config.json`. Fit scoring is in `automation/fit.py` (SWE / ML / data by default; edit the skill lists if your background is different).
