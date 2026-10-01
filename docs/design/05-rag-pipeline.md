# 05 — RAG pipeline (Phases 2 and 6)

RAG is one of four knowledge sources, used for **long-form text**: prospectuses,
information bulletins, admission brochures, policies, course descriptions, career guides.

| Question kind | Answered from |
|---|---|
| Student's own history | Memory (doc 03) — also vector search, separate collection |
| Relationships (career → degree → college) | Graph (doc 04) |
| **Numbers and dates** (fees, deadlines, seats, cutoffs, distances) | `facts` table only (doc 06) |
| Explanations, rules, eligibility wording, "what is this program like" | **RAG** |
| Things that change daily (announcements, open/closed) | Live fetch → stored as facts with provenance |

Hard rule: if a RAG chunk contains a fee or a date, it may be shown **as a quote with its
document and date**, never restated as the current value. The current value comes from `facts`.

## 1. Ingestion

```
source registry (sources, tier)
  ─► fetch (WebDataProvider): store raw bytes + sha256 + retrieved_at → source_documents
       unchanged hash → skip; changed → new version, old chunks marked superseded
  ─► extract: HTML → readability text; PDF → pdfplumber; scanned PDF → OCR (tesseract hin+eng)
       tables kept as markdown tables
  ─► clean: strip nav/boilerplate, normalise Unicode (NFC), keep Devanagari as-is
  ─► detect: language per section; academic_year and effective date (regex + LLM, validated)
  ─► chunk: structure-aware — split on headings/table boundaries, target 400–700 tokens,
       60-token overlap, never split a table row; chunk keeps its heading path as `section`
  ─► link entities: match college/program/exam names → kg keys (aliases table + fuzzy, human
       review queue below 0.9 confidence) → `entity_refs`
  ─► extract facts (separate path, doc 06): numeric fields become candidate facts, not chunks
  ─► embed (EmbeddingProvider, "passage") → doc_chunks.embedding; tsvector for keyword search
```
Runs as offline jobs in `apps/api/ingest/` (cron/systemd timer), never in a request.

## 2. Embeddings

Multilingual is required — students ask in Hindi/Hinglish about English documents.
- Default: a multilingual e5-class model (384-dim, `query:`/`passage:` prefixes), run
  locally on CPU (feasible on the Pi for queries; bulk ingestion can run on any machine).
- Alternative: an embedding API behind the same interface.
- `embed_model` is stored per chunk; changing models means re-embedding, done by a job.

## 3. Retrieval

```
query (+ language tag, intent, entity hints from the turn)
  ─► rewrite: if Hindi/Hinglish, also produce an English search query (same LLM call as intent)
  ─► filters: entity_refs ∩ hinted entities; academic_year = current or latest available; status active
  ─► hybrid search: vector top-30 ∪ keyword (tsvector) top-30 → reciprocal rank fusion → top-8
  ─► (optional) rerank with a cross-encoder if quality needs it — measured first, not assumed
  ─► return chunks with {document title, source tier, url, retrieved_at, academic_year, section}
```
The orchestrator exposes this as a tool `search_documents(query, entity?, year?)`; the LLM
must cite the document for anything it takes from a chunk (policy prompt + output check
that every cited id was actually retrieved).

## 4. Memory vectors (Phase 2)

Same machinery, different collection: `memory_items.embedding`, always pre-filtered by
`student_id` in SQL before the vector search — a student's query can never surface
another student's memory, by construction.

## 5. Evaluation

A fixed eval set (questions in en/hi/hinglish → expected documents) run in CI against a
small fixture corpus: recall@8, and "answer cites a retrieved chunk" rate. Retrieval
changes (chunk size, model, rerank) must not regress it.
