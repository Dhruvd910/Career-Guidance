"""Reading facts out of official documents with Gemini 2.5 Flash, and checking every one of them
on the Pi (docs/design/15-phase6-plan.md, P6-2, P6-5).

The model gets one document at a time — its text, or for a scanned PDF its page images — and
returns each value with the words it read it from, copied exactly, and the page. Then, on the Pi:

- **The quote must be in the document:** in its text, or for a scan, in the Pi's own OCR of it.
  A quote that isn't there is thrown away.
- **For money, the number must be in the quote.**
- **Validation per attribute:** a type and a sane range (a ₹5 hostel fee or a ₹50 lakh tuition
  is held for review), and fees need an academic year.
- **Several categories:** when a fee is given for several categories, the general one is kept.

Calls go to OpenRouter (EXTRACTION_MODEL, default google/gemini-2.5-flash); each call's tokens
and cost are reported.

**An unchanged document isn't paid for twice.** Each answer is kept under a fingerprint of the exact
request — model, instructions and the document's text or page images — in <source store>/reads/.
The same document asked the same way gets the kept answer; a changed page, a new prompt or another
model is a new request and is read again. Delete reads/ to make everything be read afresh.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.ingest.text import Extracted, contains, normalise

MONEY = {  # attribute: (lowest, highest) for a year, in rupees
    "fee.tuition.annual": (1_000, 30_00_000), "fee.hostel.annual": (1_000, 3_00_000), "fee.mess.annual": (3_000, 2_00_000),
    "fee.one_time": (100, 5_00_000), "fee.total.first_year": (5_000, 40_00_000), "placement.median_salary": (50_000, 1_00_00_000),
}
TEXT = ("fee.waiver", "facility.hostel", "facility.medical", "facility.library", "facility.labs", "facility.sports",
        "facility.internet", "location.address")
PER_YEAR = {"year": 1, "semester": 2, "month": 12, "once": 1, "course": 0.25}
GENERAL = (None, "", "all", "general", "open", "gen", "ur", "unreserved")

PROMPT = """You read official documents of Indian colleges and pull out facts a student would ask about.
Return JSON only: {"facts": [ ... ]}. Each fact:
  {"attribute": one of the names below,
   "amount": rupees as a whole number (money only), "per": "year" | "semester" | "month" | "once" | "course" (money only),
   "applies_to": the category it applies to, e.g. "general", "SC/ST", "all" (money only),
   "text": a short plain statement (non-money attributes),
   "academic_year": like "2026-27" if the document says which year (e.g. "2026 admission batch" is "2026-27"), else null,
   "quote": the exact words from the document that state it — copied character for character, a single line or table row,
   "page": the page number if the document has pages, else null}
Attributes (undergraduate programmes only: B.Tech/B.E./B.Arch/MBBS/BDS; skip PG, PhD and NRI/foreign rows):
  fee.tuition.annual, fee.hostel.annual (room or seat rent), fee.mess.annual (mess/dining), fee.one_time (charges paid
  once at admission: admission fee, caution money, deposits), fee.total.first_year (the total for the first year, if
  stated), fee.waiver (who pays less and how much), facility.hostel (are there hostels, for whom), facility.medical
  (health centre or hospital on campus, hours, doctors), facility.library, facility.labs, facility.sports,
  facility.internet, location.address (postal address of the campus), placement.median_salary (UG, with the year in
  academic_year).
Fee tables often have one column per semester or year: report the amount for one period with "per" set to match
(e.g. a row "Tuition Fee 62500 62500 ..." under semester columns is 62500 per semester). Report the main fee rows
(tuition, hostel/seat rent, mess) even when other rows exist; for waivers give the rule as "text".
Never guess or calculate: if the document doesn't state something, leave it out. An empty list is a good answer."""


@dataclass
class Read:
    attribute: str
    value: dict
    academic_year: str | None
    quote: str
    page: int | None
    flags: list[str] = field(default_factory=list)


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0
    reused: int = 0  # answers kept from an earlier read of the same document: free

    def add(self, usage: dict) -> None:
        self.calls += 1
        self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
        self.completion_tokens += int(usage.get("completion_tokens") or 0)
        self.cost += float(usage.get("cost") or 0.0)


def _kept(body: dict) -> Path:
    key = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return Path(get_settings().source_store_path) / "reads" / key[:2] / f"{key}.json"


def ask(messages: list[dict], usage: Usage, client: httpx.Client | None = None) -> dict:
    """One JSON-mode call to the extraction model through OpenRouter — or, for a request made before
    (the same document, prompt and model), the answer it got then."""
    s = get_settings()
    body = {"model": s.extraction_model, "messages": messages, "temperature": 0,
            "response_format": {"type": "json_object"}, "usage": {"include": True}, "reasoning": {"enabled": False},
            "max_tokens": 3000}  # a page's facts fit easily; a runaway reply is cut off, not paid for
    kept = _kept(body)
    if kept.exists():
        try:
            answer = json.loads(kept.read_text())["answer"]
            usage.reused += 1
            return answer
        except (ValueError, KeyError):
            pass  # a damaged file: read the document again
    if not s.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY isn't set")
    http = client or httpx.Client(timeout=180)
    try:
        r = http.post(f"{s.openrouter_base_url}/chat/completions", json=body,
                      headers={"Authorization": f"Bearer {s.openrouter_api_key}", "X-Title": "MAYA college facts"})
        r.raise_for_status()
        data = r.json()
    finally:
        if client is None:
            http.close()
    usage.add(data.get("usage") or {})
    content = data["choices"][0]["message"].get("content") or "{}"
    content = re.sub(r"^```(?:json)?|```$", "", content.strip()).strip()
    answer = json.loads(content)
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text(json.dumps({"model": s.extraction_model, "at": datetime.now(timezone.utc).isoformat(),
                                "cost": (data.get("usage") or {}).get("cost"), "answer": answer}, ensure_ascii=False))
    return answer


def messages_for(college: str, place: str, title: str, url: str, doc: Extracted, images: list[bytes] | None = None,
                 max_chars: int = 120_000) -> list[dict]:
    head = f"College: {college} ({place}).\nDocument: {title or url}\nAddress: {url}\n"
    if images:
        parts = [{"type": "text", "text": head + "This is a scanned document; its pages follow as images, in order."}]
        parts += [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(i).decode()}}
                  for i in images]
        return [{"role": "system", "content": PROMPT}, {"role": "user", "content": parts}]
    pages = doc.pages if doc.kind == "pdf" else [doc.text]
    text = "\n\n".join(f"--- page {n} ---\n{p}" if doc.kind == "pdf" else p for n, p in enumerate(pages, start=1))
    return [{"role": "system", "content": PROMPT}, {"role": "user", "content": head + "\n" + text[:max_chars]}]


def check(raw: dict, doc: Extracted) -> Read | None:
    """One value from the model, checked against the document; None if it doesn't hold up."""
    attribute, quote = str(raw.get("attribute") or ""), str(raw.get("quote") or "").strip()
    if attribute not in MONEY and attribute not in TEXT:
        return None
    page = raw.get("page") if isinstance(raw.get("page"), int) else None
    where = doc.pages[page - 1] if doc.kind == "pdf" and page and 0 < page <= len(doc.pages) else doc.text
    flags = []
    if not contains(where, quote) and not contains(doc.text, quote):
        if not doc.scanned:
            return None  # the words aren't in the document: thrown away
        flags.append("the quote isn't in the Pi's own reading of this scanned page")
    year = raw.get("academic_year")
    year = year if isinstance(year, str) and re.fullmatch(r"20\d\d-\d\d", year) else None
    if attribute in MONEY:
        try:
            amount = int(round(float(str(raw.get("amount")).replace(",", ""))))
        except ValueError:
            return None
        per = raw.get("per") if raw.get("per") in PER_YEAR else "year"
        digits = normalise(quote).replace(" ", "")
        if str(amount) not in digits:
            # Models like to add up semester columns into a year. Store what the document says instead:
            # ₹1,25,000 a year from a row of 62500s is ₹62,500 a semester.
            undone = next(((amount // d, p) for d, p in ((2, "semester"), (12, "month"))
                           if per == "year" and amount % d == 0 and str(amount // d) in digits), None)
            if undone is None:
                return None  # the number isn't in the quote
            amount, per = undone
        low, high = MONEY[attribute]
        yearly = amount * PER_YEAR[per]
        if not low <= yearly <= high:
            flags.append(f"₹{amount:,} {per} is outside the expected range for {attribute}")
        if attribute.startswith("fee.") and year is None:
            flags.append("no academic year given")
        applies = str(raw.get("applies_to") or "general").strip()
        return Read(attribute, {"amount": amount, "per": per, "applies_to": applies.lower() if applies.lower() in GENERAL else applies},
                    year, quote, page, flags)
    text = " ".join(str(raw.get("text") or "").split())
    if len(text) < 3 or len(quote) < 12 or len(quote.split()) < 2:
        return None  # a bare menu word ("Hospital") isn't evidence of what's there
    return Read(attribute, {"text": text[:400]}, year, quote, page, flags)


def read(college: str, place: str, title: str, url: str, doc: Extracted, usage: Usage,
         images: list[bytes] | None = None, client: httpx.Client | None = None) -> tuple[list[Read], int]:
    """The checked values from one document, and how many the model offered."""
    answer = ask(messages_for(college, place, title, url, doc, images), usage, client)
    offered = [f for f in answer.get("facts", []) if isinstance(f, dict)]
    checked = [r for r in (check(f, doc) for f in offered) if r is not None]
    best: dict[tuple, Read] = {}
    for r in checked:  # one value per attribute and year: the general category's, if there are several
        key = (r.attribute, r.academic_year)
        general = r.value.get("applies_to") in GENERAL if "amount" in r.value else True
        if key not in best or (general and best[key].value.get("applies_to") not in GENERAL):
            best[key] = r
    return list(best.values()), len(offered)
