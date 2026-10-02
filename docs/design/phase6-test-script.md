# Phase 6 hands-on test — college intelligence

About 30 minutes. Use MAYA on the Pi as a student would. Tell Claude "done" afterwards and it will
read what MAYA did and check it. Make sure **Edit my details** has your town (for example Indore);
distances are worked out from it, on the Pi.

## A. A college's page (8 minutes)

1. Menu → **Colleges** → search **manit** (the short name should find Maulana Azad NIT Bhopal).
   Open it.
2. Check the sections: **What it costs**, **Campus**, **Where it is and what's near**, and
   **Admissions**.
   - Every value has a coloured line under it: the source, the academic year, and *Verified today* /
     *N days ago* (green), *Stale — as of …* (amber), or *Needs verification* / *Not available* (grey).
   - Nothing should be a figure without a source.
3. Tap a fee. The dialog shows the document, page, the exact words it was read from, when it was
   fetched, and a QR code. Scan it with your phone: it should open the college's own document.
4. If a value shows **Another source says …**, the two official sources disagree. Both should be
   shown, with "please confirm with the college".
5. Places near the campus show straight-line distances, with OpenStreetMap credited.
6. Tap **Where this comes from**: every document, with its publisher and how official it is.
7. Tap **Check for updates**: it says MAYA will look again tonight.

## B. Finding colleges (7 minutes)

1. Colleges → **Find by distance, fees, hostel…** (or a career's page → **Find colleges for
   this**).
2. Try **150 km**, then **≤ ₹1 lakh**, then **Hostel**. Each time the list changes. The line at the
   top says how many colleges were **left out because something isn't known** (no location, no fee
   on record): they're counted, not guessed.
3. Sort by **Nearest**, **Lowest fee** and **NIRF rank**. There's no "best college" anywhere.
4. Pick two or three → **Compare**. Every cell shows its source and freshness, and *Not known*
   where nothing is.

## C. Asking MAYA (12 minutes, by voice)

Say these in your own words and language:

1. *"MANIT Bhopal ka hostel fee kitna hai?"* She should give the figure, saying which document
   and year it's from and how recently it was checked. If she doesn't have it, she should say so
   rather than give a number.
2. *"AIIMS Bhopal mein medical facility kaisi hai?"* An answer from the college's own pages, or
   "couldn't verify".
3. *"Mere ghar se 300 km ke andar kaunse NIT hain?"* Colleges by distance from your town, and how
   many were left out because their location isn't known.
4. *"JEE Main 2027 ka form kab aayega?"* "Not announced yet (checked …)", and last year's dates
   only as last year's.
5. *"JoSAA mein 75% wala rule kya hai?"* From JoSAA's Business Rules, naming the document.
6. *"IIT Bombay ki mess fee kitni hai?"* If it isn't known: "I couldn't verify that". She must
   never estimate it.
7. *"Sabse best NIT kaunsa hai?"* No "best"; she should offer to compare by what matters to you.

## D. Behind the scenes (3 minutes, optional)

- `apps/api/data/okf` is the knowledge bundle, in Google's Open Knowledge Format. Run
  `git -C apps/api/data/okf log` to see every change MAYA made, and open any
  `colleges/<name>/fees-2026-27.md` to read it as plain text.
- `systemctl --user list-timers maya-refresh.timer` shows the nightly refresh.

## Notes

| Check | OK? |
|---|---|
| A — every value had a source and freshness; the source dialog matched the real document | |
| A — conflicts and "not available" were shown honestly | |
| B — filters counted what they left out; no "best" | |
| C — MAYA's figures came with source and date; no invented fee | |
| C — "not announced yet" for 2027; last year's dates called last year's | |
| Any value you found wrong (give the college and the field) | |
