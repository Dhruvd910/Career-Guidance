# 15 — Phase 6 plan: College intelligence

Scope (spec §13–17, §23–24, §33, §34 Phase 6):
- a college database
- source ingestion from official documents
- fees and hostels
- admissions
- location and connectivity
- medical facilities

Every value carries its source and how fresh it is, and nothing is ever invented.

It builds on:
- the official JoSAA/MCC programme and cutoff tables (before Phase 1)
- the career graph's degree → programme → college links (Phase 4)
- the roadmap's *college exploration* step (Phase 5)
- the on-device multilingual embeddings (Phase 2)

Design: doc 06 (facts and provenance), doc 05 (RAG); schema: doc 02 §9; API: doc 07 §7.

## What exists, and what changes

| Today | Phase 6 |
|---|---|
| 739 official colleges and 1,639 programmes from JoSAA/MCC, with cutoffs. No website, address or coordinates | The same colleges, plus **official websites, addresses and coordinates**, each a fact with its source |
| 28 "researched profiles" in a JSON file: NIRF ranks, fee templates, placements and surroundings. Some come from official pages, some from secondary sites, and the surroundings have no source | Turned into **facts with honest statuses**: NIRF = government, the IIT fee page = official for IIT Roorkee only (marked "common IIT fee, not checked for this IIT" elsewhere), secondary sites labelled secondary, unsourced surroundings marked unverified until OpenStreetMap replaces them |
| Empty `fees`, `hostels`, `facilities`, `placements` and `nearby_places` tables. Their endpoints serve nothing in production | One **`facts` table** for everything externally sourced; the old tables are dropped and their endpoints answer from facts |
| MAYA says fees and hostels "aren't available yet" | MAYA answers from facts, always with the source and how fresh it is, and says plainly what's unknown. A guard stops money figures that no tool returned |
| Colleges are found by name, or through the graph by state | **Discovery**: career → degree → programmes → filters (state, distance from home, budget, exam, hostel, medical facility) → a comparison table of plain attributes, with **no "best college" score** |
| No documents | **Official documents** (information bulletins, business rules, prospectuses) searchable by meaning and keyword, quoted with their title and date |
| No admission dates | **Admission events** (application window, exam date, counselling rounds) from NTA, JoSAA and MCC, or "not announced yet" |

## Decisions

| ID | Decision | Why |
|---|---|---|
| P6-1 | **Every external value is a fact.** A fact records the entity, attribute, value, unit, academic year, source document, where in it, retrieved and verified times, status and tier. Missing values are stored as `not_available` and shown that way | Spec §14, §15, §24; doc 06 |
| P6-2 | **Automatic, with review flags** (decided by the user, 2026-10-02). A value read from an official document (tiers 1–4) is shown once its word-for-word quote is found in the document's text, labelled *read automatically from <document>*. These wait in a review list instead: values outside the expected range; values from secondary sources (tier 6) for money or dates; values read from a scanned page whose quote isn't in the Pi's own OCR text; and a fee more than 50% away from last year's | Coverage without a person in the loop for every fee; the quote check stops invented values |
| P6-3 | **Conflicts are shown, not resolved silently.** Two current values from sources of equal tier → both shown: "Source A says X. Source B says Y. These couldn't be reconciled." A lower tier never overrides a higher one | Spec §33 |
| P6-4 | **Freshness per attribute family** (doc 06 §4). Labels: *Verified today / N days ago / Stale / Needs verification*. A stale value is shown with its date and the word "stale", and MAYA says "as of <date>". Nothing stale is presented as current | Spec §16 |
| P6-5 | **Documents are read by Gemini 2.5 Flash** through OpenRouter (decided by the user; `EXTRACTION_MODEL`, roughly $4–6 for the first pass over 105 colleges). Text PDFs and pages are converted on the Pi (`pdftotext`, HTML → text). Scanned pages go to the model as images, and their quotes are checked against the Pi's own OCR (tesseract, Hindi + English). Only changed documents are read again | User's choice; a 1M-token context and image input suit long, scanned fee notices |
| P6-6 | **The first full pass covers the 105 national institutes** (IITs, NITs, IIITs, AIIMS, JIPMER, IISc, IIEST; decided by the user). Locations and nearby places cover all 739 | A predictable pilot; the pipeline is the same for the rest |
| P6-7 | **Locations come from open data.** Websites and coordinates come from Wikidata (official website P856, coordinates P625), then Nominatim. A coordinate counts only if it falls within 40 km of the college's listed city. Railway stations, airports, hospitals, bus stands, pharmacies and ATMs near campus come from OpenStreetMap through Overpass, as **straight-line distances, labelled so**. OSM attribution is shown | Tier 5 datasets, free, citable. Road distances need a routing service we don't run |
| P6-8 | **The student's home stays on the Pi.** Distance from home uses an offline GeoNames list of Indian towns (CC-BY), so a student's city is never sent anywhere | Privacy; works offline |
| P6-9 | **Fetching is polite and offline.** Fetch jobs respect robots.txt, make one request per 2 s per host, and identify the app in the user agent (no personal email). Raw documents are kept with their sha256. Jobs run from a nightly systemd timer and never inside a student's request. *Check for updates* on a college queues it for the next run | Doc 05 §1; official sites are slow and sometimes block |
| P6-10 | **RAG answers "what does this say", facts answer numbers.** A fee or date found in a document chunk is quoted with the document and its date, never restated as the current value. Current values come only from facts | Doc 05's hard rule |
| P6-11 | **A guard on money figures.** Before a sentence of MAYA's is spoken or shown, any ₹ amount in it (in digits or words, lakh or crore) must appear in that turn's tool results or in the student's own words. If it doesn't, the sentence is replaced with "I don't have a verified figure for that." | Spec §23: never fabricate fees. Prompting alone failed in Phase 5's rehearsal |
| P6-12 | Out of scope: state counselling colleges (not in the official data we have); live seat availability; reviews by students; road routing | Noted as limitations, not faked |

## Canonical attributes

| Group | Attributes |
|---|---|
| Academic | `academic.university`, `academic.established`, `ranking.nirf` (category, year, rank), programmes (existing tables, official) |
| Financial | `fee.tuition.annual`, `fee.hostel.annual`, `fee.mess.annual`, `fee.one_time` (admission, caution money, other mandatory), `fee.total.first_year`, `fee.waiver` (text) |
| Campus | `facility.hostel` (available; for whom), `facility.medical` (health centre or hospital, hours), `facility.library`, `facility.labs`, `facility.sports`, `facility.internet` |
| Location | `location.website`, `location.address`, `location.coordinates`, `near.railway_station`, `near.airport`, `near.hospital`, `near.bus_stand`, `near.pharmacy`, `near.atm` |
| Admissions | `admission.page` (official link), `admission.exam`, `admission.route` (JoSAA/MCC); events: `application_open`, `deadline`, `exam_date`, `counselling_round` |
| Placements | `placement.median_salary`, `placement.students_placed` (from NIRF's institute data, tier 1) |

Values are JSON: `{"amount": 125000, "per": "year", "applies_to": "general", "note": "…"}` for money,
`{"name": "Bhopal Junction", "km": 6.2, "kind": "straight_line"}` for places, and booleans or
short text for facilities. Money is stored as INR integers.

## Pipeline

```
source registry ─► fetch (robots, rate limit, raw + sha256) ─► text (pdftotext | HTML→text | scanned → images + OCR)
   ─► find relevant pages (keywords: fee, hostel, mess, admission, prospectus, medical, health centre…)
   ─► read (Gemini 2.5 Flash: attribute, value, academic year, verbatim quote, page)
   ─► check quote ─► validate (type, unit, range, year) ─► normalise ─► load
         load: same entity+attribute+year → supersede (old kept); different value, same tier → conflict
         flagged (P6-2) → review list, not shown
   ─► chunk + embed for RAG (official documents)
```

- **Discovery of pages:** start from the official website and admission page. Crawl at most 40
  pages per college, two links deep, following links whose text or URL matches the keywords.
  PDFs at most 25 MB.
- **Review:** `python -m app.ingest.review` lists flagged facts. Approve, reject or edit; each
  decision is recorded with who made it and why.
- **Refresh:** a nightly timer runs `python -m app.ingest.refresh`. It fetches only what's due
  under each freshness policy, marks overdue facts stale, and re-reads only changed documents.

## Steps

### Step 0 — This plan

The decisions above; doc 00's status.

### Step 1 — The facts store

- **Models and migration:** `sources`, `source_documents`, `facts`, `fact_conflicts`,
  `freshness_policies`, `admission_events`, `doc_chunks`, review decisions. `colleges` gains
  `data_origin`, `address`, `lat`, `lng` and aliases.
- **`app/facts/`:**
  - record a fact: supersede or conflict
  - the current value per attribute: lowest tier that's current and not conflicted
  - `FactView` with its freshness label
  - stale marking
- **Tests:** tiers, superseding, conflicts, freshness labels, `not_available`.

### Step 2 — What we already have, as facts

- **Official sources:** JoSAA and MCC registered as tier-3 source documents.
- **The 28 profiles become facts** with honest statuses (above). `college_profiles.json` is
  then read only by the migration.
- **Short names:** college aliases (MANIT, IIITM, IIT-BHU…) so search finds them.
- **Old tables:** dropped, and their endpoints answer from facts.

### Step 3 — Locations and nearby places (all 739)

- **GeoNames:** the India town list, offline.
- **Websites and coordinates:** from Wikidata, then Nominatim. Each coordinate is checked
  against the college's city.
- **Nearby places:** from Overpass within 15 km, the nearest of each kind, with straight-line
  distances.
- **Result:** a job, idempotent and resumable, with a report of what didn't match.

### Step 4 — Fetching and reading documents

- **Fetching:** `WebDataProvider` (httpx, robots, rate limits, retries) and the document store.
- **Text:** HTML → text, `pdftotext`, and scanned-page detection, with OCR via tesseract
  (installed with apt).
- **Page discovery:** the crawler that finds the relevant pages.
- **Tests:** against recorded fixture sites, never the live web.

### Step 5 — Facts from documents

- **Reading:** the extraction prompt and schema, the quote check, validators per attribute,
  and the review flags.
- **Pilot:** run over the 105 national institutes. The report gives coverage per attribute,
  flags and failures.
- **Review:** the review CLI.

### Step 6 — Official documents for RAG

- **National documents:** the JoSAA business rules, the MCC UG scheme and bulletin, the NEET-UG
  and JEE Main/Advanced bulletins, plus the prospectuses found in Step 5.
- **Chunks:** structure-aware, 400–700 tokens, with e5 embeddings on the Pi.
- **Search:** hybrid (pgvector + full-text, rank fusion), behind `search_documents`.
- **Evaluation:** a small set of English, Hindi and Hinglish questions with their expected
  documents.

### Step 7 — Admissions and freshness

- **Events:** admission events from the NTA, JoSAA and MCC documents. Before an announcement:
  "2027 dates not announced yet; last year: …".
- **Freshness:** the policies, the nightly `maya-refresh` systemd user timer, and the *Check for
  updates* queue.

### Step 8 — APIs

- **Discovery:** `GET /api/colleges` with the filters career, degree, state, near/radius,
  budget, exam, hostel and medical.
- **One college:** `GET /api/college/{id}` with facts grouped as Academic, Financial, Campus,
  Location and Admissions; `/sources`; `POST /refresh`.
- **Comparison:** compare with `FactView`s and conflicts.

### Step 9 — MAYA

- **Tools:** `college_facts`, `find_colleges`, `search_documents` and `admission_dates`. Each
  returns facts with a `say` line that carries the source and freshness.
- **Prompt rules:** cite and date, say "I couldn't verify that", no best college.
- **Money guard:** the P6-11 guard.
- **Context:** the roadmap's college step links to discovery.

### Step 10 — The Pi's screens

- **College page:** grouped facts, each with a source chip ("NIT Trichy fee notice 2026-27 ·
  read automatically · 3 days ago"); tapping it shows the document, date and a QR code.
- **Discovery:** filters, including distance from home.
- **Comparison:** freshness on every cell, and conflicts shown.
- **Sources:** a page listing every source document.
- **Attribution:** OSM attribution.

### Step 11 — Verification

- **Automated:** the facts rules; the guard; extraction against recorded documents; and that
  nothing from a non-official source shows without its label.
- **Live rehearsal:** on the test database. "MANIT Bhopal ka hostel fee kitna hai?", "AIIMS
  Bhopal mein medical facility kaisi hai?", "Mere ghar (Indore) se 300 km ke andar NIT
  batao", "JEE Main 2027 ka form kab aayega?", and a question whose answer isn't known.
- **Hands-on test:** `phase6-test-script.md`.

## Exit criteria

1. At least 80% of the 105 national institutes show an official tuition fee and a hostel fact
   (or a stated `not_available`). Each fact has its source, academic year and freshness label.
2. All 739 colleges have a checked location, or are listed as unmatched. Nearby stations,
   airports and hospitals are shown with straight-line distances.
3. A conflict is shown as both values with their sources. A stale value says "stale" and its
   date.
4. MAYA answers fee, hostel, medical facility and admission questions from facts with the
   source and date, and says "I couldn't verify that" when there's nothing. The money guard
   catches an invented figure.
5. Discovery goes from a career to a filtered comparison without any opaque score.
6. All Phase 1–5 tests still pass.

## Risks

- **Official sites are slow, change layout, or block automated requests** (iitb.ac.in refused a
  plain request on 2026-10-02). Failures are recorded per college and shown as "couldn't read
  the official site", never filled in.
- **Fees often vary by category, income and year of study.** The base fee is stored with
  `applies_to`, and waivers are kept as text. MAYA never computes "your fee".
- **OpenStreetMap coverage varies by city.** A missing station is `not_available`, not the
  nearest one guessed.
