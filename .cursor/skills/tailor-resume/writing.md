# Application prose

Use this for cover letters and written form answers. Resume bullets may keep colons and `\textbf{}` metrics. This file is for paragraphs.

Facts still come only from `master/resume.tex`, `master/bank.md`, and `profile.json`. Style does not license invention.

## Voice

Write like a human in ordinary-length sentences. A reader should hear one person thinking, not a résumé narrating itself, and not a short story.

- Start in the work, not in `I am applying for…`.
- Cover letters exist to say what the résumé cannot. Before writing, read `master/bank.md` **Voice and stories**. Pick one scene that overlaps this team. Sit in it long enough for cause and effect (what you noticed, why you did not trust it, what you did next, how it felt). Include a concrete object from the bank. Do not restate bullets or metrics already on the tailored resume.
- Name something specific from the JD in your own words and answer it with judgment, not a keyword dump. If a paragraph could be pasted onto a different company, rewrite it.
- Screening facts stay in screening questions. Cover letters must not mention citizenship, visa, sponsorship, relocation, or being available full-time / on-site.
- Essays must flow. Adjacent sentences should need each other. Do not stack `At Company A I… At Company B I…`.
- Do not write a string of super-short punchy lines. Let a thought finish.
- Do not write cinematic, high-temperature, or novel-like prose. A hiring manager should believe an intern wrote this after reading the posting.

## Forbidden in prose

- Em dashes and en dashes used as em dashes. Use a period, a comma, or `and`. Date ranges on the résumé may keep `--`.
- Colons used as a list or a punchline. A colon after `Dear Team,` or a form label is fine.
- Résumé sandwich (three jobs, each with its headline metric).
- Work authorization or relocation language in a cover letter or “why us / ideal internship” essay.
- `I would be excited to…` as a closing. End on the work.
- Asterisks in cover letters, essays, or chat replies about those drafts. Résumé LaTeX may keep `\textbf{}`.
- Inventing a childhood story about the company, or claiming you used their product, unless the bank says so.
- Literary voice, metaphor stacks, or “novel-like” texture. Depth is the scene, not extra adjectives.

## Cover letter shape

Read `master/bank.md` **Voice and stories** first. If no scene overlaps this team honestly, use the closest one and name the overlap in plain language. Do not invent a story about their product.

1. A specific observation about what this team actually ships or a problem named in the JD, in your own words. Not their slogan.
2. One bank scene with cause and effect, long enough that another intern could not have written it. Concrete object from the bank (an alarm name, a whiteboard, a consortium call, a false-positive choice). Not a skill list. Not three jobs.
3. Why this internship, in the same voice, tying that scene to their work.
4. Stop. No logistics paragraph.

Length about 220–380 words unless the form is shorter. Aim near 300. If it is under 200 words, the scene is too thin. If it is over 400, you are recapping the résumé or padding.

Shallow (do not write this): `I bring production debugging experience and enjoy ambiguous problems.`

Deep, only when the bank has the fact: `The LowSuccessRate alarm sat near 50% and I did not trust it. Digging showed phantom alarms leaking. That summer taught me production stays buggy even on a strong team, which is why engineers exist.`

Standalone letters go in `applications/{slug}/cover_letter.md`. Greeting may be `Dear Team,`. Sign with the name from `profile.json`. Form-box letters can live in `application_questions.md`. Same voice either way.
