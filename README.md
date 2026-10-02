# Track and Tailor

Internship season is a firehose. A hundred new SWE and ML postings hit [SimplifyJobs](https://github.com/SimplifyJobs/Summer2027-Internships) every week, each with its own ATS, its own keyword soup, and a form that asks the same five questions in a slightly different order. Sending the same PDF at all of them is how you blend into the pile.

Track and Tailor is the other loop. It watches the list for you, throws out roles you would never take, pulls the real job description, opens the apply form without submitting, and writes a **one-page resume plus drafted answers** that actually sound like the posting. You wake up, open a local dashboard, and apply.

It runs on your machine. Your master resume, phone number, and form answers never go to a website. Tailoring uses **your** Cursor login, not a shared API key.

## What you get each morning

A new Jane Street ML intern posting appeared overnight. By the time you sit down, this repo already has:

- The full JD, not the one-line GitHub table
- A fit score, so a perception/robotics intern or a trading-analyst seat never burned a tailor slot
- `applications/jane-street-machine-learning-engineer-intern/First_Last_resume.pdf`, one page, keywords from **their** posting mapped onto **your** facts
- `application_questions.md` with every Greenhouse/Lever/Ashby/Workday field it could find, answers filled from your profile, and **Needs user** on anything it must not guess (EEO, “how did you hear,” a date that is not in your files)
- A checkbox to mark it applied, plus copy buttons for the long answers so you can paste into the real form in a minute

Paste any URL yourself and it does the same thing. Login-walled posting? Paste the JD. It still tailors.

## The loop

```
SimplifyJobs JSON  →  fit filter  →  scrape JD + apply form  →  Cursor Agent
                                                              ↓
                                        one-page LaTeX PDF + drafted answers
                                                              ↓
                                        local dashboard on 127.0.0.1:8765
```

**Track.** A launchd job (default 8:00 local) diffs the SimplifyJobs Summer 2027 list. Software, ML/data, and quant only. PhD-only, hardware, PM, and trader titles are skipped. Off-season internships (not Summer 2027, May/June–Aug/Sep) and exact duplicate apply URLs are skipped. You cap how many get tailored per day so a busy morning does not melt your Cursor quota.

**Read the posting.** Stdlib scrapers hit Greenhouse, Lever, Ashby, Apple Jobs, Workday, and Oracle HCM APIs first, then JSON-LD, then HTML. If the apply form is not on the listing, a **headless** helper clicks Start Application / Apply / Apply Manually, reads the fields, and **stops**. It never opens GStack Browser, never fills the form, and never clicks Submit.

**Tailor.** Cursor Agent CLI copies your `master/resume.tex`, flips the etoolbox toggles that match the JD, writes new bullets only from `master/bank.md` and your profile, compiles with `latexmk`, and refuses to ship a two-page PDF or a sparse one-pager. Page count is checked in Python after the agent exits; overflow, heading collisions, and Cursor API timeouts re-run the agent. After the SimplifyJobs queue, the watcher also walks `applications/` and tailors any saved folder that still lacks a passing one-page resume. Cleanup will not cap-delete those folders.

**Apply from the dashboard.** PDFs, question drafts, fit reasons, and an applied toggle. Old folders age out after three weeks unless you pin them.

## What it will not do

- Invent internships, metrics, tools, or work-auth answers
- Put citizenship, visa, or relocation in a cover letter
- Host accounts for other people (this is not a SaaS; everyone brings their own resume and Cursor login)
- Replace judgment. You still click Apply on the company’s site.

That last point is the point. The tool removes the 40 minutes of scraping, keyword matching, and form archaeology. You keep the 90 seconds of “do I actually want this.”

## Setup

You need macOS, a LaTeX install (`latexmk`), and the [Cursor Agent CLI](https://cursor.com/docs/cli/overview) (`agent login`).

```bash
git clone https://github.com/josephyu12/track-and-tailor.git
cd track-and-tailor
cp master/resume.example.tex master/resume.tex
cp master/bank.example.md master/bank.md
cp .cursor/skills/tailor-resume/profile.example.json .cursor/skills/tailor-resume/profile.json
# put your facts in those three files
agent login
make internships-install
make internships-dashboard
```

`master/resume.tex`, `master/bank.md`, `profile.json`, and `applications/` are gitignored. A public fork does not publish your resume or the answers you wrote for a specific firm.

## Commands

| Make target | What it does |
|---|---|
| `internships-install` | Daily run at the configured hour, plus a dashboard that stays up on login |
| `internships-now` | Run the watcher once |
| `internships-backfill` | Tailor any saved folder that is still missing a passing one-page resume |
| `internships-dry` | Fetch and diff only; no tailor |
| `internships-report` | Rebuild today’s HTML report |
| `internships-gc` | Prune old application folders and logs |
| `internships-dashboard` | Open `http://127.0.0.1:8765/` |
| `internships-uninstall` | Remove the launchd jobs |

Edit `automation/config.json` for hour, category, daily cap, `page_retries`, and how long to keep folders. Edit `automation/fit.py` if you are not a SWE/ML intern (the default skip list assumes you are not applying to FPGA or sell-side trading seats).

Paste a JD in Cursor and say “tailor this” if you do not want to wait for the morning job. The same skill runs either way. Cover letters are opt-in: check **Draft cover letter** when adding a job, click **Make cover letter** on a saved job, or ask in chat. The watcher does not write one by default.
