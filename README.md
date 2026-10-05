# AI Career Guide — MAYA

AI-powered career guidance, exam prediction, and college discovery for Indian students
from Class 6 to college, covering JEE, NEET, and open-ended career counselling — presented
through **MAYA**, an animated, voice-first assistant on a Raspberry Pi.

Phases 1–7 of the design in `docs/design/` are built (see its `00-README.md`), plus the fixes from
the 2026-10-05 audit (`docs/design/17-audit-fixes.md`). College data is real: official JoSAA/MCC
tables and facts read from official sites, each with its source. Fictional colleges exist only in
the tests.

## Stack

- **Backend**: FastAPI + SQLAlchemy + Alembic on PostgreSQL 17 + pgvector (SQLite until Phase 2; still works without the memory features)
- **Desktop app (primary frontend)**: PySide6 (Qt) native app — `apps/desktop/`
- **Web app (kept as-is, no longer the active frontend)**: Next.js 16 + TypeScript + Tailwind — `apps/web/`
- **AI**: LLM via OpenRouter (`openai/gpt-6-luna` live, `openai/gpt-oss-120b` for background work and as fallback — see "What it costs"), speech-to-text via Groq (Whisper), text-to-speech via Cartesia — all behind provider-abstraction interfaces so any can be swapped.

## Prerequisites

- Python 3.11+
- A Linux desktop session (X11) to actually see the GUI — see "Known limitations" below.

## Setup

```bash
# Backend
cd apps/api
python3 -m venv .venv
./.venv/bin/pip install -r requirements-dev.txt
cp ../../.env.example .env   # then edit apps/api/.env — see below
./.venv/bin/alembic upgrade head
./.venv/bin/python -m app.seed.seed
./.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

```bash
# Desktop app (separate terminal, needs the backend running)
cd apps/desktop
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python main.py            # windowed
./.venv/bin/python main.py --kiosk    # full-screen, for kiosk use
```

### On the Raspberry Pi desktop (how this Pi runs)

The Pi boots to its normal desktop (labwc). Double-tap the **MAYA** icon on the desktop
(also in the menu under Education): it runs `start.sh --fullscreen`, which starts the
backend and opens MAYA full-screen. Close her with the ✕ in her header (tap twice) — that
stops the backend too — or use the **Stop MAYA** icon if she ever hangs. The launchers are
`~/Desktop/maya.desktop` and `maya-stop.desktop` (copies in `~/.local/share/applications/`).

From a terminal (on the Pi, or over SSH, when the app opens on the Pi's screen):

```
start maya              # the backend, then MAYA full screen (start maya --window: in a window)
stop maya               # both, waiting until they've really closed
restart maya            # stop, then start
maya status             # what's running
```

These are shell functions in `~/.bashrc` that call `./maya` here (`./maya start|stop|restart|status`
works without them). Logs: `.run/api.log` and `.run/desktop.log`.

The touchscreen needs the XPT2046/ADS7846 driver enabled in `/boot/firmware/config.txt`:

```
dtparam=spi=on
dtoverlay=ads7846,cs=1,penirq=25,penirq_pull=2,speed=50000,keep_vref_on=0,swapxy=0,pmax=255,xohms=150,xmin=200,xmax=3900,ymin=200,ymax=3900
```

### Database

PostgreSQL 17 with pgvector, on the Pi itself, listening on localhost only:

```bash
sudo apt install postgresql-17 postgresql-17-pgvector
sudo -u postgres psql -c "CREATE ROLE maya LOGIN PASSWORD '<password>'" \
    -c "CREATE DATABASE maya OWNER maya" -c "CREATE DATABASE maya_test OWNER maya"
sudo -u postgres psql -d maya -c "CREATE EXTENSION vector"
sudo -u postgres psql -d maya_test -c "CREATE EXTENSION vector"
cd apps/api && ./.venv/bin/alembic upgrade head      # with DATABASE_URL pointing at it
```

Moving an existing SQLite install over: put the SQLite URL in `DATABASE_URL` and the PostgreSQL
one in `POSTGRES_URL`, run `./.venv/bin/python -m scripts.sqlite_to_postgres` (safe to repeat;
it checks every table's row count), then point `DATABASE_URL` at PostgreSQL.

### Boot-to-MAYA (kiosk mode, alternative)

Instead of the desktop, a bare X session can launch MAYA directly: point `~/.xinitrc` at
`apps/desktop/run_kiosk.sh`, which starts the backend, waits for it to be healthy, then
launches MAYA full-screen. Run `startx` and it comes straight up.

### Environment variables (`apps/api/.env`)

The app works fully without any AI keys — profile, prediction, and college browsing
don't need them. Only MAYA's chat degrades (with a clear "not configured" message)
until you add:

- `OPENROUTER_API_KEY` — https://openrouter.ai/keys (LLM, OpenAI-compatible tool-calling)
- `GROQ_API_KEY` — https://console.groq.com/keys (speech-to-text)
- `CARTESIA_API_KEY` + `CARTESIA_VOICE_ID` — https://play.cartesia.ai/keys (text-to-speech)

See `.env.example` at the repo root for the full list and defaults — including
`OPENROUTER_FALLBACK_MODELS`, `MEMORY_MODEL`, `OPENROUTER_DATA_COLLECTION` and `MEMORY_ENCRYPTION_KEY`.
**Never put real keys in `.env.example`** — it's the template meant to be safe to share/commit; real
values belong only in the gitignored `apps/api/.env`.

OpenRouter (chat + tool-calling) and Groq (transcription) have been verified against real
keys. **Cartesia is MAYA's only voice** — there is deliberately no offline fallback. If its
key is wrong or its credits run out, MAYA keeps working by text and on-screen prompts but
says nothing aloud; the reason is logged in the API log as `TTS failed, replying without
audio: ...` (with `start.sh` that's `.run/api.log`). Top up or rotate the key at
https://play.cartesia.ai, then restart the backend so it picks up the new `.env`.

## Talking to MAYA — voice or typing, everywhere

- **She speaks first.** On first boot she greets you by time of day and asks for your
  details one question at a time — name, class (6 to 12, or college — then which year instead
  of the school board), board, where you live, and (for classes 11/12, where admission prediction
  needs them) domicile and category — then reads the whole lot back for confirmation. Next she
  asks, once, whether she may remember your conversations (see "MAYA's memory"). On every later boot she says good morning/afternoon/
  evening by name and moves on by herself.
- **One question per screen.** Every question takes a spoken answer, a tap, or typing, and
  has its own Back/Next; the last screen lists every answer with a Change button. Answers
  can run together — "I'm Riya and I'm in class 12" answers two questions — and saying
  "go back" works like the Back button. Later, **Edit my details** on the dashboard reopens
  the same questions.
- **Hands-free answers.** When she asks a question she listens automatically once she's
  finished speaking, and stops listening when you go quiet. Short, natural answers work:
  "Myself Priya", "I'm in eleventh", "plus two", "CBSE", "I live in Pune" (a city maps to
  its state), "OBC", "skip", "yes", "NEET".
- **Or type.** Tapping any text box stops her listening and opens the built-in on-screen
  keyboard. Its microphone key dictates into whichever box is selected, so every text field
  in the app accepts voice too — including numbers ("my rank is 45,000", "1.5 lakh").
- The keyboard is part of MAYA's own window rather than a separate program, because the
  kiosk session runs no window manager to keep a separate keyboard on top. Every page sits
  in its own scroll area, so when the keyboard takes the bottom of an 800x480 panel the page
  scrolls the box you're typing into above it instead of the window growing off screen.

## Waking MAYA, and getting back

Every screen has a header with **Back** on the left and MAYA's face on the right:

- **Tap her face** — she answers "Yes? How can I help?" and starts listening.
- **Say "Hey Maya"** (or "Hi Maya" / "Hello Maya") — the same thing, hands-free. A greeting
  is required because "Maya" alone turns up in ordinary conversation. The wake word runs
  entirely on the Pi with a small Vosk model, so no room audio leaves the device until you
  actually call her. It costs about 10% of one core and ~100MB while listening, and pauses
  while you type.
- **Interrupt her**: while MAYA is talking, say "Hey Maya", "Stop Maya" or "Maya, wait" —
  she stops mid-sentence and listens. If she'd just asked you something, what you say next
  is taken as the answer. She ignores her own voice saying her name (tested on the real
  speaker and mic: no self-triggers).
- **Back** returns to the previous screen; inside the setup questions and onboarding it steps
  back one question at a time.

The wake word needs the model and the `vosk` package:

```bash
cd apps/desktop
./.venv/bin/pip install -r requirements.txt     # includes vosk
mkdir -p models && cd models
curl -LO https://alphacephei.com/vosk/models/vosk-model-small-en-in-0.4.zip
unzip vosk-model-small-en-in-0.4.zip && rm vosk-model-small-en-in-0.4.zip
```

Without it, everything else still works and MAYA wakes on a tap.

Telling speech from noise uses the Silero VAD model (MIT licence, ~2 MB) through ONNX Runtime
(in `requirements.txt`). Without the model, MAYA falls back to a loudness check, which a fan or
traffic can fool:

```bash
cd apps/desktop/models
curl -LO https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx
``` To check what she hears in
your accent and room, say "Hey Maya" a few times at:

```bash
cd apps/desktop && ./.venv/bin/python -m app.wake_word
```

It prints every candidate and whether it counted as a wake. A name that keeps coming out
with a different spelling can be added to `VERIFIED_WAKE_WORDS` in `app/wake_word.py`, and
the accepted greetings are `WAKE_GREETINGS` in the same file.

## MAYA's memory

With permission — for anyone under 18, a parent's or guardian's — MAYA remembers across conversations.
She asks once, right after the first-run questions (**Set it up** opens the permissions; **Not now** is
recorded and not asked again); it's always in menu → **MAYA's memory** → Permissions. She remembers: the topics you're still deciding (PCM vs PCB),
what you've said about your interests, goals and constraints, a summary of each conversation, and
a timeline of your journey. Coming back after a while, she opens with where you left off.

- **Written when a conversation ends** (10 minutes without a new turn, or leaving): the background
  model (`MEMORY_MODEL`, default `openai/gpt-oss-120b`) writes the notes, and every item must quote
  what you actually said — anything it can't back up is dropped.
- **Read before every reply**: open topics, the last conversation, and the memories that matter most
  for what you just said — closest in meaning first, with recent ones and ones you've said more than
  once preferred among the equally relevant — found by a multilingual embedding model that runs on
  the Pi (no extra wait, and your memories aren't sent anywhere to be indexed). Private things
  (family, money) come up only when you're talking about them.
- **Stored encrypted**: what you say, MAYA's notes, private constraints, how-you-seem readings and a
  guardian's contact reach the database only encrypted, with a key the database never sees
  (`MEMORY_ENCRYPTION_KEY`, or the key file `apps/api/data/memory.key` made on first use). **Back the
  key up separately from the database** — without it that data can't be read.
- **Yours to see and delete**: MAYA's memory → *What she remembers* (delete any item, or
  everything) and *My journey*. Switching memory off deletes what it covered.
- **How you seem** (confused, under pressure…) is a separate permission: uncertain signals that only
  shape her tone, never a diagnosis, never shown to anyone. **Safety** is always on: if you mention
  hurting yourself or being hurt, she stops career talk, responds with care, and gives Tele-MANAS
  14416 and Childline 1098.

Guardian consent is recorded as *declared*: India's DPDP Act asks for verifiable parental consent,
which needs an identity check this app doesn't do — get legal advice before real students use it.

The embedding model (multilingual-e5-small, int8 ONNX, ~135 MB):

```bash
cd apps/api && mkdir -p models/multilingual-e5-small && cd models/multilingual-e5-small
for f in onnx/model_quantized.onnx tokenizer.json config.json; do
  curl -LO "https://huggingface.co/Xenova/multilingual-e5-small/resolve/main/$f"
done
```

## Touch: calibration and scrolling

The ADS7846 resistive panel reports raw 0–4095 values with no relation to the screen, so
until it's calibrated taps land in the wrong place. **Calibration is built into the app**:
the first time MAYA starts on an uncalibrated panel she shows five crosshairs to tap, checks
the result on the last one (it tells you how many pixels off you are), and applies it at once
— no sudo, no restart. Redo it any time from **Dashboard → Calibrate touch**. The result is
saved in `~/.config/AICareerGuide/touch_calibration.json` and re-applied every start.

On the Pi desktop it's written into labwc's `~/.config/labwc/rc.xml` (as a
`<libinput><device category="ADS7846 Touchscreen"><calibrationMatrix>` entry, next to Pi OS's own
`<touch …/>` line) and labwc is told to reload, so it holds for every program on the desktop.
In the kiosk's bare X session it's set on the running X server instead.

There's also a standalone version for a plain console (`sudo ./apps/desktop/calibrate.sh`),
which can additionally install `/etc/X11/xorg.conf.d/99-touch-calibration.conf` system-wide.

**Scrolling**: every page scrolls by dragging anywhere on it, like a phone — the panel has
no wheel and a scrollbar is a hard target for a finger. A drag past ~12px scrolls and never
counts as a tap; anything shorter is a tap and reaches the button under it normally. Lists
inside a page (a subject's chapters, say) scroll first, and hand over to the page once they
reach their end.

### Mascot animations

The mascot GIFs are 1600x960; decoding them at that size costs more than a whole CPU core
on the Pi and makes touch lag. `apps/desktop/scale_mascots.sh` writes 480px copies beside
them (one-off, ~30s, needs ffmpeg) and the app prefers those when they exist — 124% of a
core down to 15%. It's optional; without it the originals are used.

## Practice papers (mock tests in the app)

**Mock Tests** does two things: it holds a bank of practice MCQs you can sit on the device,
and it still tracks scores from tests you took elsewhere (both feed the same trends).

- **Subject test** — 10 questions from one subject, for a quick session.
- **Full-length paper** — every subject, in the same proportions as the real paper, with the
  real paper's per-question timing. The bank is smaller than a real exam, so the app says
  what it's giving you *and* what the real paper is ("63 questions in 151 min; the real JEE
  Main paper has 75 in 180"). It never passes itself off as a real paper.
- Marking is the real scheme: **+4 correct, −1 wrong, 0 unanswered**, so the guess-or-skip
  decision is the same one you'll face in the exam. The clock counts down and submits at zero.
- Answer by tapping an option; a question palette shows what's answered and jumps around;
  "Read aloud" has MAYA read the question and options out.
- Afterwards: score, subject breakdown, weakest subject, and every question reviewed with the
  right answer and why.

The questions are **written for this app, not copied from past papers** — they're marked
`practice_content` with that provenance, the same way the demo college data is marked. They
live in `apps/api/app/seed/questions_*.json`; add your own and reload with:

```bash
cd apps/api && ./.venv/bin/python -m app.seed.questions --reset
```

The loader refuses malformed entries (wrong option count, missing explanation, no exam link),
so a bad question can't silently mark students down.

## Assessments and career directions

**Menu → My assessment** (or Careers → *Find careers that fit me*) has five short checks, in
English or Hindi, taken by voice or touch and in any order:

| Check | What it measures | Time |
|---|---|---|
| What you enjoy | subjects, the kind of person you are (RIASEC), how you'd like to work and learn, what matters to you | ~6 min |
| Thinking skills | numbers, logic and words: 15 short problems, two parallel sets for retakes | ~10 min |
| Your skills | eight skills, each picked from four concrete levels ("I've built something small on my own") | ~3 min |
| Your marks | your latest marks per subject (by class and stream; also saved to your academic record) | ~2 min |
| Coding check | eight short pieces of pseudo-code to read | ~6 min |
| Space and shape | eight puzzles to picture: directions, folding, mirrors, a cut cube | ~5 min |

MAYA reads each question out and understands answers in English, Hindi and Hinglish ("mujhe
maths bahut pasand hai", "doosra wala", "sattasi percent", "peeche", "chhodo"). The Pi matches
them first; for an unusual answer to an interests or skills question, a quick AI call reads it,
and never picks an answer that isn't clear. Marks and problem answers are never left to the AI:
they're taken as heard, or tapped. Leaving midway is fine, because it picks up where you stopped.

Results are honest counts ("4 of 5 right, 1 skipped", "level 3 of 4"), never IQ-style scores or
percentiles. Problems can be gone through afterwards with the right answers. **Career
directions** put every career in a band — strong alignment, potential alignment, needs
exploration, or less likely (one tap away, never hidden) — grouped by domain. Each one has:

- **Why it may fit**, taken from your answers.
- **What it draws on**, with your own results, or "not measured yet".
- **Strengths, and things to work on**, each with a next step.
- **Questions to ask yourself**, things to try, and how people get there.

There's no overall score and no "best match"; you decide. MAYA uses all of this in
conversation. Ask "Main kitna improve hua hoon?" after a retake: she only calls a change an
improvement when it's bigger than the noise for that many questions. Every result can be deleted.

Each career also has a guide: what to do this week, how to prepare, entrance exams, free
resources (tap a link for a QR code), a day in the job, and what it pays, with sources.

The instruments are versioned JSON files in `apps/api/app/assessment/instruments/`, loaded at
first use. An instrument already in use can't be edited in place: bump its version and run
`./.venv/bin/python -m app.assessment.loader --lock`. Answers from MAYA's original quiz are
brought over with `./.venv/bin/python scripts/migrate_legacy_assessments.py` (safe to repeat).

## The career engine (knowledge graph)

MAYA knows how careers connect: the skills each needs (and what each skill builds on), the
degrees that lead there, the class 11-12 subjects and entrance exams those need (with their
official sites), what can follow, related careers, and which colleges offer a route in — from the
official JoSAA/MCC 2026 programme lists on the Pi. So she can answer:

- "What do I need to learn to become an AI engineer?" — skills in order, foundations first, with a
  project and a free course for each.
- "How do people become lawyers?" — the common route, the alternatives, and the exams.
- "PCB lu toh kya options khule rahenge?" — what each stream keeps open, what needs one more
  subject, and what closes (menu → **Stream explorer**).
- "Agar mujhe AI karna hai toh mere aas paas kaunse colleges hain?" — real colleges in your
  state, with fees, hostels and distances from the college facts where they're known.
- "Which careers need strong maths?", "biology ke bina kya kar sakte hain?", "what can I do with
  JEE?" — the graph the other way round: careers by subject, skill or exam.
- "CSE mein kaunsi specialisation hoti hai?" — the specialisations each degree comes with (Cyber
  Security, VLSI, Data Science…), read from the official programme names, with how many colleges
  offer each.

Careers is organised by area, and every career's page shows all of this, with or without an
assessment. With assessments, gaps are only claimed where something was actually measured.

The knowledge lives in `apps/api/app/knowledge/graph/*.yaml` (reviewed like code; marked "not
yet reviewed by a person" until someone signs it off), the career library and the official
tables. It's validated and loaded as one version whenever any of them changes; `python -m
app.knowledge.loader` loads it and prints what didn't match.

## Colleges: real cutoffs, compared properly

College data is real, not samples:

- **Engineering**: JoSAA 2026 opening and closing ranks, final round — all 138 IITs, NITs,
  IIITs and GFTIs, every program, category, quota and seat pool.
- **Medical**: MCC NEET-UG 2026 All-India counselling, rounds 1–2 — 601 colleges (AIIMS,
  JIPMER, government colleges' 15% All-India quota, central and deemed universities).
  2026 counselling is still running (round 3 is due 30 September), so these closing ranks
  will loosen and predictions say they lean cautious.
- **Facts from official sources** (Phase 6) for everything else, each with its source, academic
  year and how fresh it is:
  - **Fees, hostel and mess, the health centre:** read from each college's own website. The 105
    national institutes come first (IITs, NITs, IIITs, AIIMS, JIPMER, IISc, IIEST).
  - **NIRF ranks:** from the ministry's ranking pages.
  - **Where each campus is, and the nearest station, airport, hospital, bus stand, pharmacy and
    ATM:** from OpenStreetMap, as straight-line distances.
  - **Admission dates:** from NTA's bulletins.

  Unknown is said, never filled in: *not available on the official website*, *needs verification*,
  *stale — as of …*. When two official sources disagree, both are shown.

**A college's page** shows each value with a coloured line: its source, academic year and freshness.
Tap a value for the document, the exact words it was read from, and a QR code to open it on a
phone. **Check for updates** queues the college for tonight's refresh, and **Where this comes
from** lists every document.

**Find colleges** (from the colleges list, or a career's page) filters by distance from your town,
yearly tuition, exam, hostel and medical facility. You sort by nearest, lowest fee, NIRF rank or
name. There's never a "best college" score, and colleges left out because something about them
isn't known are counted on screen. **Compare** puts the same facts side by side, each with its
source.

**Ask MAYA** "MANIT ka hostel fee kitna hai?", "Indore se 300 km mein kaunse NIT hain?" or "JEE Main
2027 ka form kab aayega?". She answers from these facts with their source and date, and says when
she couldn't verify something. A guard stops any rupee figure she hasn't seen in a tool's
answer or your own words.

### Where college knowledge lives

- **`apps/api/data/okf`**: the knowledge bundle in Google's [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
  (v0.2). It has one markdown file per college per topic, every value with its sources, who
  checked it and when it goes stale. It's its own git repository, so
  `git -C apps/api/data/okf log` shows every change. The database is loaded from it.
- **`apps/api/data/sources`**: the raw documents it was read from, kept by their sha256.
- **The jobs** (`apps/api`, `.venv/bin/python -m …`):

  | Job | What it does |
  |---|---|
  | `app.ingest.official_tables` | Identities, short names and admission routes from JoSAA/MCC |
  | `app.ingest.nirf` | NIRF ranks |
  | `app.ingest.locations` | Locations and nearby places (OpenStreetMap) |
  | `app.ingest.websites` | Official websites, confirmed by the sites themselves |
  | `app.ingest.college_facts` | Fees and facilities, read with Gemini 2.5 Flash, every quote checked on the Pi |
  | `app.ingest.documents` | National bulletins, for MAYA's document search |
  | `app.ingest.admissions` | Admission dates |
  | `app.ingest.refresh` | All of the above, as due |

- **Nightly refresh:** `app.ingest.refresh` runs from a systemd user timer at 02:30, within a
  nightly reading budget of `REFRESH_BUDGET_USD`, $0.10 by default. Colleges are visited
  longest-unvisited first, and one just looked at waits (60 days, or 14 if its site couldn't be read)
  — before 2026-10-05 the same eight colleges were re-read, and paid for, every night. A document
  that hasn't changed since it was last read isn't sent to the model again: the answer is kept under a
  fingerprint of the exact request in `data/sources/reads/` (delete that folder to re-read everything).
  The weekly admission-date reading counts toward the same nightly budget. Check it with
  `systemctl --user list-timers maya-refresh.timer`; stop it with
  `systemctl --user disable --now maya-refresh.timer`.
- **Review:** values the checks hold back (odd amounts, secondary sources, unconfirmed scans) wait
  for review, decided in the bundle. Decisions are recorded as `human:<you>` in its `verified`
  field.

To reload the official data (e.g. after a database reset):

```bash
cd apps/api
./.venv/bin/python -m app.seed.josaa
./.venv/bin/python -m app.seed.mcc
```

## Roadmap and progress

**My roadmap** (menu) is built for your class and grows with you. It runs Class 10 → Class 11 →
Class 12 → Degree → Specialisation → Internship → Career, with each step's months, why it's
there and when it counts as done. A class 8 roadmap is about exploring. Class 10 adds choosing a
stream, class 12 adds entrance exams and degrees, and in college it's skills, projects and
internships. Choose a focus career (**Make this my focus** on a career's page, or tell MAYA)
and its skills come in from the career engine in the order they build on each other, with
projects. Skills you already scored strongly on are ticked, with the result as evidence.

It changes when your situation does. Each change makes a new version and says what moved and
why, and nothing is deleted: **What changed** lists the latest changes and every version so far.
You can change it yourself on the screen (**I have less (or more) time**, **Something's hard**,
**Change focus**) or tell MAYA:

- "I only have two hours a day": optional steps move later. Exam preparation never does.
- "Maths is difficult for me": a maths foundation step goes in before everything built on it.
- "I no longer want AI. I'm interested in cybersecurity": a new focus. AI's own steps are
  parked, not deleted, and anything you'd finished still counts.

MAYA tells you what would change and asks before changing anything. She also answers "Mera
next step kya hai?" and records steps you finish ("Maine Python wala step poora kar liya").

**My progress** shows each measured skill first vs now, with the results behind it ("2 of 5
right" → "5 of 5 right"). It also shows the roadmap's completion, milestones, projects and
assessments done, and the careers you've explored. Skill levels come only from assessments and
practice papers; ticking a step done is progress on the roadmap, not a skill score.

For JEE and NEET, the **exam study plan** (from the roadmap, or "Open my exam study plan" on an
exam step) still has every subject's chapters with the NCERT book and chapter to learn each from
(high-weight chapters starred). It also has free resources as QR codes, and "Practise now" opens a
practice paper in that subject.

## Where we are: MAYA as a continuing mentor

MAYA doesn't start from zero. **Where we are** (the line at the top of Home, or the menu) has:
- where you left off: the open topic and its open questions
- what's next, each item with its reason
- what you're working toward
- how you've progressed
- what you've decided

What's next is worked out without a model, from your account:
- an undecided topic
- an overdue or upcoming roadmap step
- admission dates for your exam
- a reassessment that's due: 6 months after an assessment, or when you move up a class
- news about a college on your shortlist
- a goal gone quiet
- a decision not yet in your roadmap ("Make Computer Science your focus?")

Tap **Not now** and an item stays quiet for 14 days. MAYA raises at most two of these when you
come back (after 6 hours or more), never the same one twice in a session. "Aaj kya baat karein?"
gets you the list. A decision ("PCM final hai") is only **proposed**: MAYA changes your roadmap's
focus or your stream only when you say yes.

**Save to my shortlist** is on every college's page, or tell MAYA ("IIITM Gwalior ko shortlist
mein daal do"). **My shortlist** shows each college's key facts with their source and freshness.
The shortlist counts toward the roadmap's college step.

When a session ends, its record has two parts. The summary is MAYA's notes on the conversation.
**What happened** comes from the modules themselves: roadmap versions, steps ticked, assessments
taken, colleges shortlisted. You can see both in **What MAYA remembers → Recent conversations**.
If MAYA's notes can't be written, what happened is still kept.

Conversation-based items (topics, decisions, goals) need the memory permission. The roadmap,
assessments and shortlist are your account's own data.

## One goal at a time

Pick JEE or NEET (in onboarding, or **Change goal** on the dashboard) and the app follows it:
the other exam leaves the sidebar and the dashboard, college search starts on your exam,
practice papers default to it, careers on your track come first, and MAYA is told which exam
you're preparing for so she stops offering engineering to a NEET student. Until you choose,
everything stays on show.

## What it costs, and the models

Measured on MAYA's own benchmark (2026-10-05): the same nine conversations — Hindi, Hinglish and
English; stream choice, routes, fees, colleges, safety, "where we left off" — through each model,
checking it called the right tool, answered in the student's language, never guessed their gender
and got the facts right, with the cost OpenRouter reported.

| Use | Model | Why |
|---|---|---|
| MAYA's replies | `openai/gpt-6-luna` | right tool every time, short spoken replies; about $0.0002 a turn once the prompt is cached (gpt-4o-mini: $0.0007, and it skipped tools) |
| Session notes, how-you-seem readings | `openai/gpt-oss-120b` | caught all nine things claude-haiku-4.5 did in a test session, at 1/16 of its cost |
| Fallback when the live model is down | `openai/gpt-oss-120b` | OpenRouter tries it automatically |

**Free models aren't used.** The free ones that keep students' words private were rate-limited
(4 of 6 requests refused) and took up to 36 s to start answering; the others train on what's sent,
which isn't acceptable for minors' conversations. Every OpenRouter request says
`data_collection: deny`, so a provider that stores or trains on inputs is never used.

Each model call's tokens and cost go in the API log (`app.llm`) and `/api/metrics`; each turn's are
saved on the reply. The prompt is ordered for the providers' caches (rules first, the student's steady
context next, what changes each message last), which is most of the saving.

## Health, logs and limits

- **`/api/health`**: the database, each AI service (configured, its circuit breaker, its last failure),
  the embedding model; `"status": "degraded"` when something's down. Never includes keys.
- **`/api/metrics`** (from the Pi itself only): requests by route with p50/p95 latency, model calls with
  tokens and cost, interruptions, rate-limited requests.
- **Logs** are JSON lines (`LOG_FORMAT=json`, or `text`), each with the request id that's also returned
  as `X-Request-ID`. Logins, permission changes, deletions and profile edits are written to the
  `app.audit` log by id and field name, never the values.
- **Rate limits**: 30 AI requests a minute per student (replies, voice, speech), 10 logins a minute per
  address; over that, 429 with Retry-After (spoken turns get a "give me a few seconds").
- **Production** (`ENVIRONMENT=production`) refuses to start with the development `JWT_SECRET_KEY`.

## Known limitations (honest, not glossed over)

- **The GUI is developed headlessly**: work happens over SSH with no X server, so screens
  are verified by constructing them under Qt's offscreen platform and driving them
  programmatically — real, but not the same as watching them render. The app itself runs
  fine on the attached 800x480 HDMI panel via `startx`.
- **Small-screen layout**: the kiosk panel is 800x480. Pages are sized/scrolled to fit
  that, and kiosk mode sets the window geometry explicitly because the kiosk X session
  runs no window manager (so `showFullScreen()` alone has nobody to honor it).
- **State counselling isn't covered yet**: NEET data is MCC's All-India counselling only;
  85% of government medical seats go through each state's own counselling. JoSAA covers
  central institutes only, not state engineering colleges (e.g. through JEE Main-based state
  counselling).
- **College facts start with the 105 national institutes.** Their official websites are read
  for fees and facilities. The other 600-odd colleges have cutoffs, NIRF ranks where ranked,
  locations and nearby places, and say *not available* for what hasn't been read yet.
  Official sites are slow, change layout and sometimes block automated reading; a site that
  couldn't be read is reported, never filled in.
- **Wikidata isn't used:** its API now requires a contact address in every request, and none is
  shared. Locations come from OpenStreetMap alone, so some colleges have no known location yet.
- **Name spelling by voice**: Whisper can mis-hear uncommon names (in testing it heard a
  synthetic voice's "Dhruv" as "D.H. Ruff"). That's why MAYA reads your name back and the
  name box stays tappable to fix it.
- **The wake word hasn't been tested on a real voice saying "Maya"**: there's no working
  text-to-speech key here to generate a sample, so it's verified the other way round — real
  speech *without* her name never wakes her (a regression test feeds a clip that used to).
  Use `python -m app.wake_word` to check it hears you.
- **Audio (this Pi 5)**: the speaker is on a USB sound card and the microphone is a separate USB
  mic. A Pi 5 has no 3.5mm jack, and with no PipeWire ALSA bridge ALSA's default output is the
  HDMI screen — so MAYA was silent until `pipewire-alsa` was installed. For interrupting MAYA by
  talking, run `python3 apps/desktop/setup_audio.py` once: it installs a WebRTC echo canceller into
  PipeWire so her mic doesn't hear her own voice. Without it she can still be interrupted with
  "Stop Maya".
- **Audio (original kiosk Pi)**: a USB sound card provides the microphone; playback is the Pi's 3.5mm jack.
  Both go straight through ALSA (no PulseAudio/PipeWire is installed, so Qt Multimedia's
  output had nowhere to go). The mic only supports 44.1/48kHz, so it records natively and
  resamples to 16kHz for Whisper. Speech detection was tested with synthetic audio and a
  real silent-room recording on this hardware — not yet with a real person talking.

## Running the tests

```bash
cd apps/api
./.venv/bin/pytest
```

The tests never call a real AI service (the keys are blanked for them) or touch the real database.
Covers: prediction-engine band classification (🟢/🟡/🔴) against known synthetic cutoffs,
auth register/login, one full register → profile → exam-profile → predict → college-detail
integration test, practice papers (subject mix, marking, review, and the rules that answers
never reach the device before submission and one student can't open another's paper), the
career assessment (a clinical-minded student gets MBBS, skipped questions stay neutral),
JoSAA/MCC seat rules (category ranks, home-state and female-only pools, Paper 2 programs),
rank estimates from percentile or score, college profiles and comparison, and the voice
endpoints' rule that only the device itself may use them without logging in.

```bash
cd apps/desktop
./.venv/bin/pip install -r requirements-dev.txt
./.venv/bin/pytest
```

Covers: understanding spoken answers (names, classes including "plus two"/PUC, boards,
states and cities, categories, yes/no, exam choice, numbers like "1.5 lakh"), speech
detection on synthetic audio, MAYA's speak → listen → answer sequencing and cancellation,
the on-screen keyboard driven by simulated taps, which setup questions get asked and what
they save, the two-stage wake-word detector (including a real-model check that ordinary
speech doesn't wake her), drag-to-scroll (taps still reach buttons, drags don't click them),
the touch-calibration maths, sitting a practice paper, interrupting MAYA mid-sentence, and
the college comparison and college pages.

## Project layout

```
apps/api/       FastAPI backend (see docs/architecture.md for module breakdown)
apps/desktop/   MAYA — the PySide6 desktop app (primary frontend)
apps/web/       Next.js web app (earlier iteration, kept but not the active frontend)
docs/           Architecture plan and API reference
```

## Resetting data

```bash
cd apps/api
./.venv/bin/python -m app.seed.seed --reset    # exams, courses, careers, practice questions (no colleges)
./.venv/bin/python -m app.seed.josaa           # then the real engineering cutoffs
./.venv/bin/python -m app.seed.mcc             # and the real medical cutoffs
```
