# 18 — Usability fixes: getting around, learning, and tests that fit the student (2026-10-05)

A student's-eye review found MAYA hard to find your way around: no clear map from one screen to
the next, Back that went to the wrong place, nowhere to learn what a career needs, and tests that
were too easy, always the same, and asked a computer-science student about hospitals.

## What changed

| Problem | Fix | Where |
|---|---|---|
| Back from the first onboarding question opened the first-run form (name, class, category), even after the tests were done | Onboarding's Back is the previous screen; only after "Do you know your career?" does it step back, by un-answering that question. Changing details is *Settings → Edit my details*, or the link on onboarding's screen | desktop `pages/onboarding.py`, `pages/setup.py` |
| From one career to a related one, Back skipped the first career (same screen, so not remembered) | Every screen with different contents is a new history entry; one-off flags (`wake`, `ask`, `fresh`…) aren't replayed on the way back | desktop `main_window.py` (`navigate`, `_entry`, `TRANSIENT`) |
| No quick way home; Back was the only way out | A **Home** button (house) on every inner screen; Home clears the trail | desktop `main_window.py` (`_go_home`) |
| The top Back inside a test stepped back a question, so leaving a test took many taps | The top Back leaves (the test picks up where you stopped next time); **Previous question** below the answers steps back inside it, and is hidden when there's nothing to go back to | desktop `pages/assessment_runner.py` |
| Eight tiles in no order, and names that changed from screen to screen ("My assessment", "Assessment", "My assessments") | The home screen in two numbered rows — *1 Find your path*: My Tests, Career Paths, My Roadmap, Learn; *2 Get there*: Colleges, Exams, Mock Tests, My Progress — and the same name on the tile, the screen's title and every button that leads there. The settings menu is down to five items | desktop `pages/dashboard.py`, `main_window.py` |
| Nothing explained how the parts connect | **How MAYA works** (the **?** on the home screen): each part in order with an *Open* button, and what Back, Home, MAYA, ✕ and ⚙ do | desktop `pages/guide.py` |
| A career was predicted, but nowhere said where to learn for it | **Learn**: the topics for a career in order, each with how you did, one English and one Hindi video for *that topic*, a YouTube search for more, and things to try. Tap a video for a QR code. Career pages and roadmap steps link to it at that topic; MAYA's `learning_videos` tool names videos in conversation | api `knowledge/learning.py`, `routers/learn.py`, `knowledge/tools.py`; desktop `pages/learn.py` |
| Thinking skills was 15 fixed questions, the same every time, and easy | Adaptive banks: 150 thinking-skills problems (50 each for numbers, logic and words), 50 coding, 50 spatial, 10 per level at 5 levels. One level up after a right answer, one down after a wrong one, from a start set by class; random within the level; a retake avoids questions seen before | api `assessment/service.py`, `assessment/spec.py`, `scripts/build_question_banks.py` |
| A JEE student heading for computer science was asked about biology and hospitals | Goal-aware questions: the student's track (exam → roadmap focus career's domain → stream) skips the questions written as not applying to it (`applies_to.skip_for_tracks`) | api `assessment/tracks.py`, `instruments/interests.v2.json` |
| An "&" on a button vanished: Qt reads it as a keyboard-shortcut marker, so "Class 9 & 10" showed as "Class 9 _10" (video titles, MAYA's suggestion, the next-step strip, mock-test options like "Both A & B") | `button_text()` escapes it where data goes into a plain button; `link_button` already draws its text with a label | desktop `widgets/common.py`, `pages/learn.py`, `dashboard.py`, `maya.py`, `practice.py` |
| Emoji (👋 🔴 🔎, and 🔥 in video titles) drew as empty boxes on the Pi | Removed from MAYA's own text; stripped from video titles when shown | desktop `pages/greeting.py`, `pages/exam.py`, `pages/learn.py` |

Migration: `0c610f2e0d9a` (`assessment_attempts.track`). Instruments: `aptitude@2`, `coding_check@2`,
`spatial@2`, `interests@2` (in `lock.json`). Earlier attempts keep their versions and results.

## Adaptive tests

- **Levels.** Every problem has a difficulty 1–5. The bank must have at least `per_dimension`
  questions at every level of every dimension, since a student can stay at one level throughout
  (checked when the file loads).
- **Start.** `adaptive.start` maps class to a level: classes 6–7 start at 1, 8–9 at 2, 10 and up
  at 3. The coding check starts a level lower for classes 8–10 (most students haven't coded yet).
- **Next question.** Dimensions take turns. The level moves ±1 on the last answer to that
  dimension (a skip counts as wrong) within 1–5. A question is picked at random from the level,
  seeded by attempt and position so going back shows the same question, preferring questions this
  student hasn't seen in earlier attempts. A level with nothing new left repeats an old question;
  one with nothing left at all borrows from the nearest level.
- **Score.** `adaptive_correct`: each answer earns its level if right, level − 1 if wrong;
  score = points / (asked × 5). Right at level 5 every time scores 1.0; moving between levels 3
  and 4 scores 0.6. The result shows the highest level answered right and the count: "level 3 of 5
  · 3 of 5 right". A change between two attempts counts as real only beyond 0.15.
- **Content.** `scripts/build_question_banks.py` generates numbers, logic, series, spatial and
  coding problems in English and Hindi, and carries 50 hand-written word problems. Every coding
  answer is checked by running the code, answer positions are spread (no option position holds more
  than 35% of answers), and every item's Hindi must be written in Devanagari.

## Learn

- **Which career.** The one asked for; otherwise the roadmap's focus career; otherwise the strongest
  (then potential) career direction; otherwise none, and Learn points to the tests.
- **Which topics.** The career's skills from the knowledge graph, in the order its skill path
  builds them, each with the student's standing from their results: *You're strong here*, *On
  track*, *Work on this* or *Not tested yet*.
- **Which videos.** `knowledge/videos.json`: 106 videos for 66 topics, found by
  `scripts/find_videos.py`. It searches YouTube per topic in English and Hindi, prefers trusted
  teaching channels, drops shorts, videos under 4 minutes, low-view videos and career-advice or
  clickbait channels, needs a Hindi pick to be in Hindi, and checks each video against YouTube's
  oEmbed. Videos picked and found wrong by hand go in `REJECTED`. Reasoning topics use school-level
  sources (olympiad and NTSE mental-ability material), not bank or railway exam coaching.
- **On the Pi.** There is no browser: tapping a video shows its QR code to scan with a phone. MAYA
  never reads a link aloud; she names the video and channel and offers to open Learn.

## Not fixed here

- Videos get taken down: re-run `scripts/find_videos.py` now and then. A topic with no good video
  keeps its YouTube search link (legal reasoning, today).
- The adaptive levels are the question writer's judgement, not calibrated on students yet. Once
  enough attempts exist, a question's level should come from how often students at each level
  get it right.
- The career and direction screens' buttons are still English-only, as before.
