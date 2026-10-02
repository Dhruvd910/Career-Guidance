# 16 — Phase 7 plan: The continuous mentor

Scope (spec §2's lifecycle, §7, §21, §22, §34 Phase 7, §37): bring together memory, assessment,
progress, roadmap, the career graph, college information and counselling, so that MAYA:
- **starts every session from the student's whole situation,**
- **ends it by updating that situation from what actually happened,** and
- **knows, between sessions, what's worth raising next.**

Spec §37 lists what the student should be able to ask, and MAYA must always be able to answer:

1. Who am I?
2. What have I discussed before?
3. What was I confused about?
4. What decisions have I made?
5. What am I working toward?
6. How have I progressed?
7. Where did my last session stop?
8. What should we discuss next?

## What exists, and what's missing

| Built | Missing |
|---|---|
| Phase 2: session summaries with the §22 fields, counselling threads (§7 fields), "where we left off" opening, goals, interests, constraints, timeline, consent | The summary's `roadmap_changes`, decisions and goals are the model's account, not what happened. Nothing outside memory feeds the opening |
| Phase 3: assessments and directions | No idea of when a reassessment is due (spec §2: progress → **reassessment** → roadmap update) |
| Phase 5: roadmap, next step, progress | Not raised between sessions: an overdue step waits until the student asks |
| Phase 6: college facts, admission dates | No shortlist on screen (the saved-items API exists, unused). No "your colleges' fees just came out". No "applications open in 12 days" |
| Each module puts its own lines into MAYA's context | No single place that ranks what matters *now* |

## Decisions

| ID | Decision | Why |
|---|---|---|
| P7-1 | **The brief.** `mentor.brief(student)` answers the eight questions from the modules' own data, each answer citing where it came from (a thread, a summary, the roadmap, an assessment). It's for the opening line and the "Where we are" screen. Each module still owns its own part of MAYA's context; there's no single giant prompt | Spec §37; "separate but connected modules" |
| P7-2 | **The agenda.** A deterministic, ranked list of what's worth raising, each item with a reason, its source and the screen it opens. Items: an undecided counselling topic; an overdue or upcoming roadmap step; a reassessment that's due; admission dates for the student's exam in the next 30 days, or the next cycle announced; a shortlisted college whose facts changed; a goal gone quiet; a decision not yet reflected in the roadmap. No model decides what's on it | Testable, explainable; the student can see why |
| P7-3 | **Never nag.** An item raised is remembered (when, how often). MAYA raises at most two items at the start of a session, and none twice in a session. The student can mark one done or "not now", which snoozes it for 14 days | Spec §5, care over pressure |
| P7-4 | **What happened goes in the record as it happened.** At session end, the deterministic facts of the session become part of its summary, beside the model's account: roadmap versions made, steps ticked, assessments taken, colleges shortlisted, dates looked up. `roadmap_changes` comes from the roadmap, never from the model | The record must be true |
| P7-5 | **Decisions are proposed, not applied.** A session decision that names a career or stream ("decided: PCM", "going for CSE") becomes an agenda item: "Make CSE your roadmap focus?". MAYA asks; the student says yes | Same rule as Phase 5 (P5-3): the student decides |
| P7-6 | **Reassessment.** An instrument is due again 6 months after it was last taken, or when the student moves up a class. A retake updates the roadmap (Phase 5) and progress, and MAYA says what changed, honestly (noise-aware, from Phase 3) | Spec §2's loop |
| P7-7 | **The shortlist.** Colleges the student saves (on screen or by telling MAYA) are part of their state: in the brief, in MAYA's context with their key facts, and as evidence for the roadmap's college exploration step. A change in a shortlisted college's facts since the student's last session is an agenda item | Spec §17 → §2's "college discovery" in the journey |
| P7-8 | **Consent as before.** The brief and agenda read only what the student's consents allow. Memory items and threads need long-term memory; roadmap, assessments and shortlist are account data. Agenda marks are account data, deleted with the account | Phase 2 and Phase 3 rules |
| P7-9 | Out of scope: notifications off the Pi (SMS, email, push), parents' views, a counsellor dashboard | Needs consent design and contacts the product doesn't hold |

## Steps

### Step 0 — This plan

### Step 1 — The brief and the agenda (`app/mentor/`)

- `agenda_marks` (student, key, first and last raised, times raised, status
  open/done/dismissed, snoozed until), migration.
- `brief()`: the eight answers.
- `agenda()`: collectors per module, ranking, marks, snoozing.
- Tests per collector, and for ranking and never-nag.

### Step 2 — Shortlist and reassessment

- **Shortlist:** service and MAYA tools (`my_shortlist`, `shortlist_college`); the roadmap's
  college exploration step gets evidence; changed facts since the last session.
- **Reassessment:** the due rule; after a retake, a "what changed" summary for MAYA.

### Step 3 — Session end

- Deterministic session facts (from the session's time window: roadmap versions, progress
  changes, assessment attempts, saves, tools used), merged into the session summary
  (schema version 2).
- Decisions naming a career or stream become agenda proposals.

### Step 4 — MAYA

- An agenda part in her context (at most three items, with reasons).
- The opening line from the brief and the agenda.
- The `what_next` tool ("Aaj kya baat karein?").
- Prompt rules: pick up where we left off; raise an item once; accept "not now".

### Step 5 — The Pi

- Home becomes **Where we are**: last time, what's next, coming up (dates, reassessment), as tap
  targets, each with "done" and "not now".
- **Save to my shortlist** on a college page, and **My shortlist** with each college's key facts
  and their freshness.

### Step 6 — Verification

- **Automated:** collectors, never-nag, consent, deterministic summaries, proposals not
  applied.
- **Multi-session rehearsal** with the real model on the test database, with time moved forward
  between sessions:
  1. PCM vs PCB left open.
  2. Ten days later: "where we left off", a shortlisted college's fee change.
  3. Seven months later: reassessment due, retake, what changed, roadmap update.
- **Hands-on test:** `phase7-test-script.md`.

## Exit criteria

1. A returning student hears where they left off, including an undecided topic, the roadmap's
   next step and anything due. MAYA never starts from zero.
2. "Aaj kya baat karein?" gets the agenda's top items with reasons. "Not now" keeps an item quiet
   for 14 days.
3. A session's summary records what actually changed (roadmap versions, assessments, shortlist)
   from the modules themselves.
4. A decision about a career becomes a proposal, never an automatic change.
5. Six months after an assessment, or after moving up a class, a reassessment is offered. After
   it, the roadmap and progress update, and MAYA explains what changed.
6. The shortlist appears on screen and in MAYA's answers, with its facts' freshness.
7. All Phase 1–6 tests still pass.

## As built (2026-10-02)

Steps 0–6 are built. 495 server tests pass on SQLite and on PostgreSQL, and 388 Pi-app tests pass.
MAYA has four new tools: `what_next`, `update_agenda`, `my_shortlist`, `shortlist_college`.
`set_my_stream` was added after the rehearsal (see below).

**What's where:**
- `app/mentor/`:
  - `agenda.py`: seven collectors, ranking, never-nag
  - `brief.py`: the eight answers
  - `shortlist.py`
  - `session_facts.py`: what happened in a session
  - `context.py`: MAYA's part
  - `details.py`: setting the stream on a yes
- Two migrations: `agenda_marks`, and `session_summaries.happened`.
- API:
  - `GET /api/mentor/brief` and `GET /api/mentor/agenda`
  - `POST /api/mentor/agenda/mark`
  - `GET/POST/DELETE /api/mentor/shortlist`
- On the Pi:
  - **Where we are**, with the home screen's top line leading to it
  - **Save to my shortlist** on every college page
  - **My shortlist**
  - **Recent conversations** (in What MAYA remembers) now shows **What happened**

**Rehearsal.** The real model ran on the test database, using public data and an invented student
(Riya, class 10, Indore). The clock was moved forward between sessions: every stored date and time
was moved back together.

1. **Session 1 (PCM vs PCB, left open).** She took the aptitude check during the session. The
   summary recorded two unresolved questions, no decisions, and, from the modules, "Took 'Thinking
   skills'" and the roadmap step it completed.
2. **Ten days later.** She had shortlisted IIITM Gwalior, and a new tuition fee was recorded for it.
   - The agenda: the open topic; "IIITM Gwalior: its official sources updated this since your last session: tuition fee"; the
     roadmap's next step.
   - The opening recalled the open topic and her father.
   - "Aaj kya baat karein?" called `what_next` and offered the topic and the fee news.
   - She decided PCM and computer science. MAYA offered to update the roadmap and didn't change
     anything.
3. **Seven months later, in class 11.** The agenda: "Make Computer Science & Software Engineering
   your roadmap's focus?", "Set your stream to PCM?" (both proposals, 58) and "Retake 'Thinking
   skills' — you took it in class 10; you're in class 11 now" (55).
   - The opening raised the two proposals.
   - "Haan, focus bana do" called `set_roadmap_focus` (roadmap version 3). "Stream bhi PCM kar do"
     called `set_my_stream`.
   - After the retake, "Kya badla?" called `compare_assessments`.
   - The summary recorded the roadmap version, the steps completed and the assessment taken, all
     from the modules. Then the proposals and the retake left the agenda.

**Found by the rehearsal and fixed:**
- "computer science" didn't match the CSE career, so a decided career was never proposed. Fixed
  with aliases in `careers.yaml`.
- MAYA said "maine tumhara stream PCM kar diya" with no tool that could. Fixed with the
  `set_my_stream` tool (on a yes; the roadmap is rebuilt for it). Its note says not to claim a
  roadmap change that didn't happen.
- "Aaj kya baat karein?" didn't always call `what_next`, because everything had already been
  raised in the opening. MAYA's context now always says to call it, even for items already
  mentioned.
- The opening line used "tu", which is too familiar. Its instructions now ask for "aap" or "tum",
  and for MAYA's own feminine forms, as the main prompt already did.
- A reassessment marked done hid every later one for the same instrument. The key is now per
  attempt (`reassess:aptitude:41`).
- The stream proposal read "your details still say nothing". It now reads "it isn't in your
  details yet".
- In one run, the notes model returned malformed JSON twice, and the session was written with
  nothing at all. That lost what happened too. Now what happened is kept, under "MAYA couldn't
  write notes for this session", with no topics or memories (`writer._what_happened_only`).
- "New since your last session: Tuition fee" came out as "its fee you should find out today". It
  now reads "Its official sources updated this since your last session: …".

**Changes from the plan:**
- Stream decisions can be applied by MAYA on a yes. The plan only had them proposed; the screen
  route (Edit my details) also works.
- **Where we are** is its own screen, reached from a line at the top of Home, rather than replacing
  Home. Home's other tiles stay where students already know them.

**Known limits:**
- A goal set in conversation stays "quiet" until the notes model links a later session to it. In
  the final rehearsal, "Build roadmap around computer science" was still active after the roadmap
  was built. So only one quiet goal is raised at a time (the quietest), at the lowest priority, as
  "still working toward it?". "Done" lets the next one through.
- MAYA's Hindi still slips into masculine forms now and then: for herself ("samajh gaya", once in
  three rehearsal runs) and for a student who has used feminine forms. That's the chat model,
  despite the rule.
- Agenda marks are kept per student and deleted with the account. There are no reminders off the
  Pi (P7-9).
