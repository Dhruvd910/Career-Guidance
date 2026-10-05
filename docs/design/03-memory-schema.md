# 03 — Memory schema (Phase 2)

Memory is **not** "save every transcript". Transcripts (`messages`) are raw material. What
the counsellor actually uses is distilled into five layers, each with its own shape,
lifetime and retrieval method.

| Layer | Table(s) | Holds | Written | Read |
|---|---|---|---|---|
| 1. Profile | `student_profiles`, `student_interests/goals/constraints`, `academic_records` | Structured facts about the student | Explicit statements (confirmed), assessments, profile edits | Every turn (small snapshot) |
| 2. Working | in-process + `messages` | This session's turns | Every turn | Every turn (token-budgeted) |
| 3. Counselling | `counselling_threads`, `session_summaries` | Open topics, decisions, next steps | Session end | Session start; when topic matches |
| 4. Episodic | `student_events` | Timeline of what happened, when, why | When it happens | Timeline UI; "how have I changed" questions |
| 5. Semantic | `memory_items` (+ embedding) | Loose but useful facts: "parents prefer PCB", "built a line-follower robot" | Session end | Relevance search per turn |

## 1. Shapes

### Counselling thread — the unit of "where we left off"
A thread is one counselling *topic* that can span many sessions.
```json
{
  "id": 41, "topic_key": "stream_choice", "title": "PCM vs PCB",
  "status": "open", "decision_status": "leaning",
  "current_position": "Leaning PCM because of interest in computers; worried about parents preferring PCB.",
  "open_questions": ["Is biology interest real or parent-driven?", "Would PCMB keep both doors open?"],
  "actions_agreed": [{"action": "complete aptitude assessment", "status": "done", "event_id": 902}],
  "next_step": "Review aptitude result together; talk through how to discuss with parents",
  "opened_session_id": 12, "last_session_id": 19, "last_touched_at": "2026-09-28T17:40:00+05:30"
}
```

### Session summary (spec §6.2/§22), produced at session end
```json
{
  "schema_version": 1,
  "summary": "Discussed PCM vs PCB again after the aptitude result…",
  "important_context": ["Class 10, CBSE", "Strong logical reasoning (0.84)"],
  "decisions": [{"thread_id": 41, "decision": "leaning PCM", "firmness": "tentative"}],
  "unresolved_questions": ["How to raise this with parents"],
  "new_interests": [{"node_key": "domain:robotics", "evidence": "talked about building robots for 5 minutes"}],
  "goals": [{"title": "Finish Python basics module", "kind": "skill"}],
  "next_steps": ["Try 2 Python mini projects", "Talk to parents"],
  "roadmap_changes": [{"op": "add", "node_key": "explore:robotics", "reason": "new interest"}],
  "student_state": {"signals": [{"signal": "anxious_about_parents", "confidence": 0.6}], "note": "inferred, uncertain"},
  "threads_touched": [41]
}
```

### Episodic event
```json
{"event_type": "CAREER_INTEREST_ADDED", "occurred_at": "…", "actor": "ai",
 "entity_type": "kg_node", "entity_id": "career:ai_ml_engineer",
 "payload": {"strength": 0.8}, "reason": "Student expressed strong interest in AI", "session_id": 19}
```
`event_type` CHECK list: `CAREER_INTEREST_ADDED`, `CAREER_INTEREST_REMOVED`,
`ASSESSMENT_COMPLETED`, `GOAL_CREATED`, `GOAL_COMPLETED`, `ROADMAP_CREATED`,
`ROADMAP_UPDATED`, `SKILL_IMPROVED`, `SKILL_DECLINED`, `COUNSELLING_SESSION`,
`DECISION_MADE`, `DECISION_REOPENED`, `COLLEGE_SHORTLISTED`, `COLLEGE_REMOVED`,
`MILESTONE_COMPLETED`, `PROFILE_UPDATED`, `CONSENT_CHANGED`.

### Student state (per turn, `turn_analyses`) — spec §5
```json
{"intent": "career_decision", "topic": "stream_choice",
 "emotion_signals": [{"signal": "confusion", "confidence": 0.72}, {"signal": "frustration", "confidence": 0.41}],
 "underlying_concerns": [{"concern": "fear_of_disappointing_parents", "confidence": 0.55}]}
```
Rules: signals are a fixed vocabulary of *conversational* signals (confusion, frustration,
pressure, social comparison, low confidence, excitement, disengagement) — never clinical
terms. Every signal has a confidence; anything < 0.5 is not used for style. Signals adjust
tone and follow-up questions in the *next* reply; they are **never** written to the profile,
never shown to parents, and only an aggregate goes into the session summary.

**Escalation**: a separate, conservative check (keyword + LLM classifier) for self-harm or
abuse disclosures. On a hit, the counsellor stops career mode, responds supportively, gives
Indian helpline information (Tele-MANAS 14416), and suggests a trusted adult. The system does
not diagnose, assess risk levels, or continue as if nothing was said.

## 2. Write path (session end, background job)

```
session messages ─► Extractor (LLM, JSON-schema output, temperature 0)
                     ├─ session summary
                     ├─ thread updates (match existing threads by topic_key; create/resolve/reopen)
                     ├─ candidate profile changes ─► only if the student stated them explicitly
                     ├─ candidate memory items
                     └─ candidate events
                  ─► Validator: schema check; each item must cite ≥1 message id as evidence;
                     drop items whose evidence quote isn't in the transcript (anti-hallucination)
                  ─► Reconciler: dedupe vs existing memory (embedding sim > 0.9 → update, not insert);
                     contradiction → old item `superseded`, event DECISION_REOPENED etc.
                  ─► Write in one transaction + events
```
Real-time writes during the session are limited to things the student explicitly asks
for ("remember that I only have 2 hours a day") and profile fields confirmed on screen.

## 3. Retrieval (per turn)

Never "load everything". A **retrieval plan** comes from the turn's intent:

| Intent (examples) | Plan |
|---|---|
| `stream_choice` "Should I choose PCM?" | profile: class, stream, subjects, marks · threads where topic_key=`stream_choice` · last assessment scores for maths/bio/logical · interests · constraints of kind `family_expectation` · decisions on this topic · semantic top-k on query |
| `skill_progress` "How am I progressing in Python?" | skill_measurements for `skill:python` (series) · roadmap nodes referencing it + progress · projects with that skill · semantic top-k filtered to node_key `skill:python` |
| `next_step` "Mera next step kya hai?" | active roadmap version → first not-done node on the critical path · open threads' next_step |
| `college_search` | profile location/budget/constraints · current career direction · shortlist events |
| `small_talk` / unknown | profile snapshot + open-thread titles only |

Then: candidates → score = `relevance + 0.03·recency + 0.03·salience` (built 2026-10-05 as a sum, not a product: this model's similarities sit within ~0.1 of each other, so a multiplier would let an unrelated but recent memory win) → pack into the token
budget (doc 01 §4), each item tagged with its id so the reply and the summary can cite it.
The intent classifier is the same cheap LLM call as the state analyzer (one call returns both).

## 4. "Where we left off" (spec §7)

On `conversation/start`:
1. Load open/parked threads ordered by `last_touched_at`, the last `session_summary`, and
   pending `actions_agreed`.
2. Compute the **current counselling state** (a view, not a stored copy):
   `current_counselling_topic, current_problem, decision_status, open_questions,
   previous_actions, next_step, last_session` — from the most recent open thread.
3. If the last session was > 6 h ago and a thread is open, the opening line is a recap plus a
   check-in, generated from that state only:
   *"Last time we were discussing PCM vs PCB. You were interested in computers, but also
   worried about what your parents expect. We hadn't decided yet. Has anything changed?"*
4. If nothing is open, greet by name and reference the roadmap's next step instead.
The student can say "let's talk about something else" and the thread stays `open`.

## 5. Privacy & control

- Consent gates: no `memory_items` / `turn_analyses` are written without `long_term_memory`
  / `emotion_signals` consent (guardian consent for minors). Without it, the app still works
  with layers 1–2 only.
- "My memory" screen: the student can see every memory item and event, correct or delete
  them; deletion is real (row delete + embedding delete), recorded in `data_requests`.
- `sensitivity=sensitive` (family conflict, health access needs, finances) → never sent to the LLM
  unless the question is about it. Built 2026-10-05: memories, constraints, summaries, concerns and
  messages are encrypted columns for everyone (app/core/crypto.py), not only the sensitive rows.
- Retention: raw audio is not stored by default; transcripts retained N months (config),
  summaries/events kept until deletion.
