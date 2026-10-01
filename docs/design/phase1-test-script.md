# Phase 1 hands-on test

About 20 minutes with MAYA on the Pi's screen. Open MAYA from the desktop icon, go to
**Talk to MAYA** (or say "Hey Maya"), and tap **Speak** before each question — or just answer
when she asks you something. Timings are logged automatically; you only need to note what
*didn't* work. When done, tell Claude "done" (it reads the logs and fills in the results).

## A. Language (≈ 8 turns)

Say each one; her reply should come back in the same language — Hindi or Hinglish for the
Hindi/Hinglish ones (in Devanagari or English letters, both fine), English for the English ones.

| # | Say | Expect |
|---|---|---|
| A1 | "Mujhe samajh nahi aa raha ki mujhe engineering karni chahiye ya nahi." | Hindi/Hinglish; asks you something back before recommending |
| A2 | "What are my options if I don't want engineering?" | English, straight after A1 — and still about your situation |
| A3 | "Mujhse JEE nahi ho raha, sab friends ka ho raha hai." | Hindi/Hinglish, kind, asks what's hard — not just "study more" |
| A4 | "Mera next step kya hai?" | Hindi/Hinglish |
| A5 | "मुझे डॉक्टर बनना है लेकिन बायोलॉजी मुश्किल लगती है।" | Hindi |
| A6 | "Which is better for me, data science or software engineering?" | English |
| A7 | Answer one of her questions with just "haan" or "ok" | Keeps the language you were using |
| A8 | Your own question, in whatever mix you'd normally speak | Same mix back |

Note any turn where the reply was in the wrong language: ________

## B. Interrupting her (10 tries)

Ask something with a long answer — "Tell me about all the IITs and what each is known for" —
and while she's talking, **just start speaking** ("Wait — what about NITs?"). She should stop
within about a third of a second of you starting, and answer your new question.

Tries where she **didn't** stop: ____ / 10. Tries where she stopped but answered the wrong
thing: ____

## C. Not interrupting (≈ 3 minutes of her speaking)

Ask for long answers three or four times and let her finish. While she talks, cough, clap
once, move a chair, tap the table — she should **not** stop for any of those, and she should
never stop on her own.

Times she stopped by herself or for a noise: ____

## D. After an interruption

Interrupt her early in a long answer, then ask "What were you saying?" She should only refer to
what you actually heard, not claim she'd already told you the rest.

OK? ____

## Pass criteria (from the Phase 1 plan)

| Check | Pass |
|---|---|
| Reply language (A) | ≥ 7 of 8 right |
| End of your speech → her first sound (logged) | median ≤ 3 s, 90th percentile ≤ 4.5 s |
| Interrupting (B) | stops in ≥ 9 of 10 |
| Not interrupting (C) | 0 stops |
| After an interruption (D) | doesn't assume you heard the rest |
| No voice service; server restart mid-conversation | ✅ drilled 2026-10-01: answers on screen and says why; reconnects in ~3 s to the same session |
