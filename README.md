# AI Career Guide — MAYA

AI-powered career guidance, exam prediction, and college discovery for Indian students
(Class 8–12), covering JEE, NEET, and open-ended career counselling — presented through
**MAYA**, an animated voice-assistant desktop app.

This is a **Phase 1 + MVP** build (see `docs/architecture.md` for the full phasing
rationale). Every college/cutoff/fee figure in the seeded dataset is **clearly marked
demo data** — fictional college names, not real admissions numbers.

## Stack

- **Backend**: FastAPI + SQLAlchemy + Alembic, SQLite for now (portable to PostgreSQL later)
- **Desktop app (primary frontend)**: PySide6 (Qt) native app — `apps/desktop/`
- **Web app (kept as-is, no longer the active frontend)**: Next.js 16 + TypeScript + Tailwind — `apps/web/`
- **AI**: LLM via OpenRouter, speech-to-text via Groq (Whisper), text-to-speech via Cartesia — all behind provider-abstraction interfaces so any can be swapped. OpenRouter and Groq are verified against real keys; Cartesia is MAYA's only voice (see below).

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

The touchscreen needs the XPT2046/ADS7846 driver enabled in `/boot/firmware/config.txt`:

```
dtparam=spi=on
dtoverlay=ads7846,cs=1,penirq=25,penirq_pull=2,speed=50000,keep_vref_on=0,swapxy=0,pmax=255,xohms=150,xmin=200,xmax=3900,ymin=200,ymax=3900
```

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

See `.env.example` at the repo root for the full list and defaults. **Never put real
keys in `.env.example`** — it's the template meant to be safe to share/commit; real
values belong only in the gitignored `apps/api/.env`.

OpenRouter (chat + tool-calling) and Groq (transcription) have been verified against real
keys. **Cartesia is MAYA's only voice** — there is deliberately no offline fallback. If its
key is wrong or its credits run out, MAYA keeps working by text and on-screen prompts but
says nothing aloud; the reason is logged in the API log as `TTS failed, replying without
audio: ...` (with `start.sh` that's `.run/api.log`). Top up or rotate the key at
https://play.cartesia.ai, then restart the backend so it picks up the new `.env`.

## Talking to MAYA — voice or typing, everywhere

- **She speaks first.** On first boot she greets you by time of day and asks for your
  details one question at a time — name, class, board, where you live, and (for classes
  11/12, where admission prediction needs them) domicile and category — then reads the
  whole lot back for confirmation. On every later boot she says good morning/afternoon/
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

## Careers: MAYA's assessment and career guides

**Careers → Find careers that fit me** starts a conversation, not a form of 1–10 sliders:
MAYA asks about 30 questions — what you enjoy, how you like to work, and deep-dives into
physics, chemistry, biology, maths and computers ("Would you rather treat patients or
research diseases?"). Tap an answer or say it; "skip" and "go back" work too. Follow-up
questions depend on earlier answers.

Every career gets a fit score, and the result says plainly which is the **best match** and
which are **not a natural fit**, with the reasons from your answers and what to watch out
for. Tap a career for its guide: what to do this week, how to prepare step by step, entrance
exams, free resources (tap a link to get a QR code for your phone), a day in the job, what
you can become, the future of the field, and what it pays — with the sources for the pay.

## Colleges: real cutoffs, compared properly

College data is real, not samples:

- **Engineering**: JoSAA 2026 opening and closing ranks, final round — all 138 IITs, NITs,
  IIITs and GFTIs, every program, category, quota and seat pool.
- **Medical**: MCC NEET-UG 2026 All-India counselling, rounds 1–2 — 601 colleges (AIIMS,
  JIPMER, government colleges' 15% All-India quota, central and deemed universities).
  2026 counselling is still running (round 3 is due 30 September), so these closing ranks
  will loosen and predictions say they lean cautious.
- **Researched profiles** for the 28 colleges students compare most (top IITs and NITs,
  AIIMS, JIPMER, leading government medical colleges): NIRF 2025 rank, fees with waivers and
  hostel costs, placements (median and highest package, with the year and source), the
  teaching hospital, and what's around the campus — nearest airport and station, local
  transport, daily needs. Kept in `apps/api/app/seed/data/college_profiles.json`, every
  figure with its source; add a college by adding an entry under its official name.

**Compare** (pick 2–4 colleges on the Colleges page, or tap **+ Compare** on predicted
colleges) opens with a verdict — best ranked, lowest fees, best median package, hardest and
easiest to get into — then ranking, getting in, cost, placements and surroundings side by
side. A college's own page lists its closing ranks for your category, program by program.

To reload the official data (e.g. after a database reset):

```bash
cd apps/api
./.venv/bin/python -m app.seed.josaa
./.venv/bin/python -m app.seed.mcc
```

## Roadmap

The roadmap follows your exam: milestones, a pacing plan, and every subject's chapters with
the NCERT book and chapter to learn each from (high-weight chapters starred), plus free
resources — NCERT, NTA's own practice, YouTube channels — as QR codes. "Practise now" opens a
practice paper in that subject.

## One goal at a time

Pick JEE or NEET (in onboarding, or **Change goal** on the dashboard) and the app follows it:
the other exam leaves the sidebar and the dashboard, college search starts on your exam,
practice papers default to it, careers on your track come first, and MAYA is told which exam
you're preparing for so she stops offering engineering to a NEET student. Until you choose,
everything stays on show.

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
- **Most colleges have cutoffs but no researched profile**: 28 are researched; for the rest
  the app says so rather than guessing, and points to the official website.
- **Name spelling by voice**: Whisper can mis-hear uncommon names (in testing it heard a
  synthetic voice's "Dhruv" as "D.H. Ruff"). That's why MAYA reads your name back and the
  name box stays tappable to fix it.
- **The wake word hasn't been tested on a real voice saying "Maya"**: there's no working
  text-to-speech key here to generate a sample, so it's verified the other way round — real
  speech *without* her name never wakes her (a regression test feeds a clip that used to).
  Use `python -m app.wake_word` to check it hears you.
- **Audio**: a USB sound card provides the microphone; playback is the Pi's 3.5mm jack.
  Both go straight through ALSA (no PulseAudio/PipeWire is installed, so Qt Multimedia's
  output had nowhere to go). The mic only supports 44.1/48kHz, so it records natively and
  resamples to 16kHz for Whisper. Speech detection was tested with synthetic audio and a
  real silent-room recording on this hardware — not yet with a real person talking.

## Running the tests

```bash
cd apps/api
./.venv/bin/pytest
```

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
./.venv/bin/python -m app.seed.seed --reset    # exams, careers, sample data
./.venv/bin/python -m app.seed.josaa           # then the real engineering cutoffs
./.venv/bin/python -m app.seed.mcc             # and the real medical cutoffs
```
