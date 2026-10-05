# 17 — Audit fixes (2026-10-05)

An audit of MAYA against the full product spec found the architecture and Phases 1–7 in place, with
these gaps. Each is fixed here unless marked otherwise.

## What changed

| Gap (spec §) | Fix | Where |
|---|---|---|
| The live model skipped required tools and guessed students' gender (§21, §28) | Benchmarked models on MAYA's own scenarios; `openai/gpt-6-luna` live, `openai/gpt-oss-120b` background + fallback; the gender rule moved into the per-message language note; MAYA never mentions "tools" to students | `core/config.py`, `ai/language.py`, `ai/orchestrator.py` |
| Cost: the same 8 colleges' websites re-read every night; haiku-4.5 for notes; prompt layout defeating caches | Refresh back-off (`refresh_attempts`, longest-unvisited first); notes and signal readings on the background model; prompt ordered rules → student → history → per-message parts; per-call tokens/cost logged and on `/api/metrics` | `ingest/refresh.py`, `providers/llm.py`, `providers/registry.py` |
| The design's "only changed documents are read again" wasn't built: unchanged pages and bulletins were sent to Gemini again; the weekly bulletins were outside the nightly budget | Answers kept under a fingerprint of the exact request (model + prompt + document) in `data/sources/reads/`; `admissions.run` takes the refresh's spending and limit | `ingest/read.py`, `ingest/admissions.py`, `ingest/refresh.py` |
| Students' data could reach providers that store or train on it (§28, §30) | Every OpenRouter request carries `provider.data_collection: deny` | `providers/registry.py` |
| Memory ranked by similarity only (§7; doc 03 promised more) | `similarity + 0.03·recency + 0.03·salience` over the 4k nearest; recency halves every 90 days | `memory/store.py` |
| Classes 6–7 and college students couldn't sign up (§15) | Class 6–12 or College (+ year) on the Pi and in the API; `education_stage` validated; onboarding branches; MAYA's prompt covers every stage | `schemas/student.py`, `services/student_service.py`, desktop `pages/setup.py` |
| Memory was off for everyone and never offered (§6) | Asked once in onboarding, right after the basics; "Not now" is recorded | `services/student_service.py`, desktop `pages/onboarding.py` |
| No rate limits, request ids, structured logs, metrics, provider health, audit log (§29–30) | `core/ratelimit.py`, `core/observability.py`, `/api/health`, `/api/metrics`, `app.audit` | `main.py` and routers |
| Sensitive data stored in plain text (§30; doc 03 promised encryption) | Fernet-encrypted columns: messages, memories, constraints, summaries, concerns, guardian contacts. Key outside the database; `scripts/encrypt_existing.py` for older rows | `core/crypto.py`, `core/types.py` |
| Production could run with the development JWT secret | Refused at start | `core/config.py` |
| "Which careers need X?" couldn't be answered from the graph (§10) | `careers_needing` (subject, skill or exam → careers, and how) | `knowledge/graph_store.py`, `knowledge/tools.py` |
| No specialisations layer (§10) | `degree_specialisations`, read from the official JoSAA/MCC programme names | same |
| "data science", "designer", "dentist"… didn't resolve to careers | Everyday and Hindi aliases in `careers.yaml` | `knowledge/graph/careers.yaml` |
| `colleges_offering` told the model fees weren't collected (stale since Phase 6) | Points to `college_facts` / `find_colleges` | `knowledge/tools.py` |
| No spatial reasoning (§8) | `spatial.v1`: 8 voice-friendly puzzles, `aptitude:spatial`, used by architecture, design, civil, mechanical, aerospace and the graph's spatial skill | `assessment/instruments/spatial.v1.json` |
| API contract routes missing (§25) | `GET /api/colleges/{id}/programs`, `GET /api/colleges/{id}/admissions`, `POST /api/counselling/session` | routers |

Migrations: `1ee76da8faa2` (refresh attempts), `56c77f1714be` (text columns for ciphertext).

## The model benchmark

Nine scenarios on a copy of the production database (real colleges, facts and graph): which careers
need maths; a Hinglish PCB question; a Hindi "doctor" question; the route to data science; a hostel fee;
AI colleges near the student; a gender-neutral Hinglish coding question; a self-harm disclosure; and
"I want counselling again" with a three-week-old open topic. Checks: the expected tool, the reply's
language and script, no gender guessing, the content (no medicine among maths careers, the helpline,
NEET, a figure from the facts), and OpenRouter's reported cost.

| Model | Checks | $/turn | First word (median) | Verdict |
|---|---|---|---|---|
| openai/gpt-4o-mini (before) | 26/28 | 0.00074 | 3.9 s | skipped tools in Hindi and for coding; guessed gender |
| **openai/gpt-6-luna** | 27/28 (28 by hand) | 0.00079 first, ~0.00018 cached | 4.4 s | chosen: concise, right tools |
| openai/gpt-oss-120b | 24/28 | 0.00041 | 4.4 s | skipped tools; fine for background work |
| nvidia/nemotron-3.5-lightning | 28/28 | 0.00074 | 5.7 s | markdown and 6× longer replies: bad aloud, costlier speech |
| qwen/qwen3.7-flash | 27/28 | 0.00045 | 8.7 s | slow; guessed gender |
| deepseek/deepseek-v4-flash | 27/28 | 0.00136 | 3.6 s | dearer; guessed gender |
| google/gemma-4-31b-it | 27/28 | 0.00260 | 14.9 s | far too slow for voice |
| google/gemini-2.5-flash-lite | 19/27 | 0.00067 | 8.2 s | skipped tools, wrong language |
| qwen/qwen3.8-27b:free | — | 0 | up to 36 s | 4 of 6 requests rate-limited |

Free models that train on inputs (the NVIDIA ones) are excluded by the data policy. Session notes,
on one 9-turn Hinglish session against a 9-point key: haiku-4.5 9/9 $0.0079; gpt-oss-120b 9/9
$0.0005; gpt-6-luna 9/9 $0.0012; gpt-4o-mini 7/9.

After the change, a 3×3 re-run of the Hindi and Hinglish scenarios on Luna passed every check.

## The document reader benchmark (EXTRACTION_MODEL)

14 real official documents already on the Pi (7 text PDFs, 2 web pages, 5 scanned fee notices; IITs,
NITs, IIITs, AIIMS), each model reading them with MAYA's own prompt and checks. Key: the 71 money values
the Pi had accepted from them (quote-checked; itself not perfect — Gemini re-reading agreed with 79%).

| Model | Values found | Text | Scans | Cost / document | Notes |
|---|---|---|---|---|---|
| **google/gemini-2.5-flash** (kept) | **56/71** | 41/52 | 15/19 | $0.0042 | no failures |
| openai/gpt-6-luna | 47/71 | 33/52 | 14/19 | $0.0008 | best of the cheaper ones; misreads per-semester fees as yearly |
| google/gemma-4-31b-it | 44/71 | 32/52 | 12/19 | $0.0007 | doubles some totals; 25 s a document |
| qwen/qwen3.7-flash | 30/71 | 18/52 | 12/19 | $0.0003 | misses most text-document fees |
| openai/gpt-oss-120b | 22/52 | 22/52 | — | $0.0004 | text only; needs reasoning on (MAYA's reader turns it off) |
| google/gemini-2.5-flash-lite | 25/71 | 18/52 | 7/19 | $0.0009 | 5 of 14 replies were broken JSON |

The quote check can't catch a period read wrongly (the number *is* in the quoted row), so a weaker reader
means wrong fees, not only fewer. With unchanged documents no longer re-read, Gemini 2.5 Flash costs about
$2–3 a year here; Luna would save under $2 a year. Gemini 2.5 Flash stays.

## Not fixed here

- **A real student hasn't used it.** Nothing replaces docs/design/phase*-test-script.md with a person.
- **Human review** of the curated career graph (470 nodes marked unreviewed) and of the new spatial
  puzzles' wording.
- **29 careers.** More need sourced long-form guides (pay, day in the job) and review — content work.
- **Emotional signals** still shape the *next* reply: reading them before the reply would add an LLM
  call to every turn's wait. The reply itself sees the message, and safety stays synchronous.
- **Legal review** of guardian consent under the DPDP Act (consent is "declared", not verified).
- **Embeddings** of private memories aren't encrypted (they have to be searched).
