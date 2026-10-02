"""A one-time move of the 28 hand-researched college profiles (app/seed/data/college_profiles.json)
into the OKF bundle, keeping only what can be attributed honestly:

- **The shared IIT and NIT fees** come from IIT Roorkee's and NIT Tiruchirappalli's own pages. For
  any other institute they're the common structure, not that college's notice, so they go in as
  *needs verification*, saying so. A checked fee from the college's own notice ranks above them.
- **Fees from a secondary site** (Careers360) wait for review, as P6-2 says.
- **NIRF ranks** aren't copied: `app.ingest.nirf` reads them from NIRF itself.
- **Not imported:** placements, the unsourced surroundings, websites and founding years. Later
  steps read these from proper sources (NIRF's institute data, OpenStreetMap, Wikidata).

    python -m app.ingest.profiles
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingest.publish import college_entity, publish
from app.models.college import College
from app.okf.facts import Document, Value

PROFILES = Path(__file__).resolve().parent.parent / "seed" / "data" / "college_profiles.json"
TIERS = {"nirf_eng_2025": 1, "nirf_med_2025": 1, "iit_fees": 2, "nit_fees": 2, "mbbs_fees": 6, "iit_highest": 6}
PUBLISHERS = {"iit_fees": ("iit-roorkee", "IIT Roorkee"), "nit_fees": ("nit-tiruchirappalli", "NIT Tiruchirappalli"),
              "mbbs_fees": ("careers360", "Careers360")}
OWN = {"iit_fees": "Indian Institute of Technology Roorkee", "nit_fees": "National Institute of Technology, Tiruchirappalli"}
YEARS = {"nit_fees": "2026-27"}  # the NIT Trichy notice is for 2026; IIT Roorkee's page gives no year


def _researched_at() -> datetime:
    """When the profiles were written: the file's last commit, or its modification time."""
    out = subprocess.run(["git", "log", "-1", "--format=%cI", "--", str(PROFILES)], cwd=PROFILES.parent,
                         capture_output=True, text=True, check=False).stdout.strip()
    if out:
        return datetime.fromisoformat(out).astimezone(timezone.utc)
    return datetime.fromtimestamp(PROFILES.stat().st_mtime, tz=timezone.utc)


def values(db: Session) -> tuple[dict, list[str]]:
    data = json.loads(PROFILES.read_text(encoding="utf-8"))
    sources, templates = data["sources"], data["templates"]
    at = _researched_at()
    colleges = {c.canonical_name: c for c in db.execute(select(College)).scalars()}
    out, notes = {}, []
    for name, profile in data["colleges"].items():
        college = colleges.get(name)
        if college is None:
            notes.append(f"{name}: no such college in the official data")
            continue
        fees = profile.get("fees")
        key = fees if isinstance(fees, str) else (fees or {}).get("source")
        fee = templates.get(fees) if isinstance(fees, str) else fees
        if not fee or not fee.get("tuition_per_year") or key not in sources:
            continue
        publisher_key, publisher = PUBLISHERS.get(key, (key, sources[key]["name"]))
        doc = Document(publisher_key, publisher, TIERS.get(key, 6), sources[key]["url"], sources[key]["name"], at)
        shared = isinstance(fees, str) and OWN.get(key) != name
        common = {"locator": f"the common fee structure, as {publisher} publishes it — not checked for this college"
                  if shared else None,
                  "generated_by": "maya-migration/college-profiles-v1", "verified_by": None, "at": at}
        tier = TIERS.get(key, 6)
        status = "unverified"
        flags = [f"a fee from a secondary source ({publisher})"] if tier == 6 else []
        vals = [Value("fee.tuition.annual", {"amount": int(fee["tuition_per_year"]), "per": "year", "applies_to": "general"},
                      doc, YEARS.get(key), status=status, flags=flags, **common)]
        if fee.get("waivers"):
            vals.append(Value("fee.waiver", {"text": fee["waivers"]}, doc, YEARS.get(key), status=status, flags=flags,
                              **common))
        out[college_entity(college)] = vals
    return out, notes


def run(db: Session, root=None) -> dict:
    vals, notes = values(db)
    report = publish(db, vals, "Fees from the hand-researched profiles, marked for verification", root)
    report["notes"], report["colleges"] = notes, len(vals)
    return report


if __name__ == "__main__":
    from app.core.db import SessionLocal

    with SessionLocal() as session:
        result = run(session)
    print({k: result[k] for k in ("colleges", "changes", "commit", "loaded")}, result["notes"], result["problems"][:10])
