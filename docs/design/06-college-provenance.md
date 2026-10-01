# 06 — College data & provenance model (Phase 6)

## 1. Principle

Every externally sourced value is a **fact**: one attribute of one entity, with where it
came from, when, for which academic year, and how sure we are. Domain tables (`fees`,
`hostels`, `facilities`, `nearby_places`) become views over facts. Missing is a value too:
`not_available` is stored and shown, never filled in.

```json
{
  "entity_type": "college", "entity_id": 1234,
  "attribute": "fee.hostel.annual",
  "value": 120000, "unit": "INR/year", "currency": "INR",
  "academic_year": "2026-27", "effective_from": "2026-07-01",
  "source": {"name": "IIT Example — Fee Structure 2026-27", "tier": 2,
             "url": "https://…/fees-2026-27.pdf", "locator": "page 3, table 2"},
  "retrieved_at": "2026-09-30T10:12:00+05:30",
  "verified_at": "2026-09-30T10:12:00+05:30", "verified_by": "auto",
  "status": "verified", "confidence": 0.95
}
```

## 2. Pipeline (spec §14)

```
Official sources ─► fetch (raw stored, hashed) ─► extract (HTML/PDF/table parsers, LLM-assisted
for messy PDFs) ─► validate ─► normalise ─► canonical fact ─► facts / graph edges / doc_chunks
```
- **Extract** produces *candidate* facts with a `source_locator` (page/table/selector).
  LLM-assisted extraction must return the verbatim snippet; a candidate whose snippet is not
  found in the document text is rejected.
- **Validate**: type/unit/range checks per attribute (a hostel fee of ₹12 or ₹1.2 crore is
  flagged), academic year present for time-sensitive attributes, entity resolved.
- **Normalise**: canonical attribute names (`fee.tuition.annual`, `fee.hostel.annual`,
  `fee.mess.annual`, `fee.application`, `facility.hostel.available`, `facility.medical`,
  `location.lat`, `near.railway_station`, `admission.deadline`…), INR integers, ISO dates.
- **Load**: a new value for the same (entity, attribute, academic_year) supersedes the old
  one (kept, linked via `superseded_by`); a different value from another source of equal
  or higher tier for the same year opens a `fact_conflicts` row.
- Human review queue for: confidence < 0.8, conflicts, first fact from a new source.

The canonical record is the "Open Knowledge Format" layer of spec §14: a normalized
representation, never the source of truth itself — the stored raw document is.

## 3. Source tiers (spec §33)

| Tier | Kind | Examples |
|---|---|---|
| 1 | Government | Ministry of Education, NIRF, state govt orders |
| 2 | Institution official | college/university website, prospectus, fee notice |
| 3 | Official admission portal | JoSAA, MCC, NTA, state counselling portals |
| 4 | Regulator | AICTE, NMC, UGC, COA, BCI |
| 5 | Reliable structured datasets | AISHE, data.gov.in, OpenStreetMap (for places) |
| 6 | Reputable secondary | major newspapers/education portals — shown as "secondary source" |

For a given attribute, the shown value is from the lowest-numbered tier with a non-stale,
non-conflicted fact. Tier 6 alone is shown with an explicit "not from an official source" label.

## 4. Freshness

`freshness_policies` per attribute family:

| Attribute | Refresh | Stale after |
|---|---|---|
| `admission.*` dates/deadlines | daily during admission season, weekly otherwise | 7 days in season |
| `fee.*` | each admission cycle | when a new academic year starts with no new fact |
| `cutoff.*` | each counselling round | next round published |
| `facility.*` | yearly | 400 days |
| `location.address`, coordinates | rarely | 3 years |
| `near.*` (stations, hospitals, transport) | yearly, or live map provider | 400 days |

Display labels from `verified_at`: *Verified today* · *Verified 7 days ago* · *Verified 30
days ago* · **Stale** · **Needs verification**. A stale fact is shown with its date and the
word "stale", and the AI must say "as of <date>" — never present it as current.

## 5. Conflicts (spec §33)

When two current facts disagree, both are returned to the UI and the LLM:
> "The 2026-27 fee notice (college website, Sept 2026) says ₹1,20,000. The admission
> brochure (JoSAA, June 2026) says ₹1,10,000. These could not be reconciled — please confirm
> with the college."

## 6. What the AI receives

Tools return facts, never bare numbers:
```json
{"attribute": "facility.medical", "value": "On-campus health centre, 24x7",
 "status": "verified", "source_name": "Official College Website", "source_url": "…",
 "verified_label": "Verified 7 days ago", "academic_year": "2026-27"}
```
and `{"attribute": "near.hospital", "status": "not_available"}` when unknown. The policy
prompt requires mentioning source + freshness for any fee/date/facility claim, and saying
"I couldn't verify that" for `not_available`. An output check flags replies containing ₹
amounts or dates that don't appear in that turn's tool results.

## 7. College discovery (spec §17)

career → degree (graph) → eligible programs → filters (location/distance, budget from
fee facts, exam, academic eligibility, hostel, medical facility, transport) → **comparison
table of transparent attributes**, each cell with its freshness label. No "best college"
score. The existing JoSAA/MCC predictor stays as one more column ("closing rank last year
for your category"), with its own explanation.

## 8. Migrating today's data

| Today | Becomes |
|---|---|
| JoSAA 2026 / MCC 2026 cutoffs (official CSVs) | stays in `cutoffs`, source rows registered in `sources`/`source_documents` (tier 3) |
| `seed/data/college_profiles.json` (28 researched colleges, sourced) | facts, each with its listed source; any value without a URL → `unverified` |
| Demo colleges from `seed.py` (`is_demo_data=True`) | `tests/fixtures/` only; `data_origin='fixture'`; production startup check refuses them |
| `nearby_places` sample rows | dropped from production; re-sourced from OpenStreetMap (tier 5) with distances computed, as facts |
