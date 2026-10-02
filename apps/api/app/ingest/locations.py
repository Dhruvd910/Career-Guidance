"""Where each college is, and what's near it (docs/design/15-phase6-plan.md, P6-7), from
OpenStreetMap (tier 5). Wikidata isn't used: its API now requires a contact address in every
request, and the user chose not to share one (2026-10-02).

- **Overpass** first, when the college's town is known: every named college, university and
  hospital within 30 km of it, the best name match (abbreviations expanded) taken if it's close
  enough. **Nominatim** otherwise: a few phrasings of the name, a hit counting only if its name
  resembles the college's and it lies within 40 km of the town (or, with no known town, nearest
  a town in the right state). A website tag, if any, is kept too.
- **Overpass** (OpenStreetMap): the nearest railway station, airport, hospital, bus stand,
  pharmacy and ATM, as straight-line distances. None within the search radius is stored as
  not available, saying how far it looked.

A point that fails the checks isn't used; it's reported. Runs in batches, each one a bundle
commit, so it can stop and pick up again.

    python -m app.ingest.locations [--limit N] [--refresh]
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import geo
from app.facts import store
from app.ingest.fetch import Fetched, Fetcher
from app.ingest.publish import college_entity, publish
from app.models.college import College
from app.okf.facts import Document, Value

NOMINATIM = "https://nominatim.openstreetmap.org/search"
OVERPASS = "https://overpass-api.de/api/interpreter"
MAX_KM = 40
NEAR = {  # attribute: (radius in metres, Overpass filters)
    "near.railway_station": (25000, ['["railway"="station"]["station"!~"subway|light_rail|monorail"]']),
    "near.airport": (100000, ['["aeroway"="aerodrome"]["iata"]']),
    "near.hospital": (10000, ['["amenity"="hospital"]']),
    "near.bus_stand": (15000, ['["amenity"="bus_station"]']),
    "near.pharmacy": (3000, ['["amenity"="pharmacy"]']),
    "near.atm": (2000, ['["amenity"="atm"]']),
}
STOP = {"of", "and", "the", "for", "in", "at", "a", "an", "india"}
# Official names abbreviate freely ("Govt. Dental Coll. & Hospt."); OpenStreetMap usually doesn't.
ABBREVIATIONS = {"govt": "government", "gov": "government", "hosp": "hospital", "hospt": "hospital",
                 "coll": "college", "collegel": "college", "collage": "college", "dent": "dental", "inst": "institute",
                 "sci": "sciences", "sce": "sciences", "med": "medical", "univ": "university", "res": "research",
                 "mem": "memorial", "edu": "education", "tech": "technology", "engg": "engineering"}


def _tokens(text: str) -> set[str]:
    return {ABBREVIATIONS.get(t, t) for t in geo.norm(text).split() if t not in STOP}


def similarity(a: str, b: str) -> float:
    x, y = _tokens(a), _tokens(b)
    return len(x & y) / len(x | y) if x and y else 0.0


ACRONYMS = ((r"\bAIIMS\b", "All India Institute of Medical Sciences"), (r"\bIIIT\b", "Indian Institute of Information Technology"),
            (r"\bIIT\b", "Indian Institute of Technology"), (r"\bNIT\b", "National Institute of Technology"),
            (r"\bGMC\b", "Government Medical College"), (r"\bBHU\b", "Banaras Hindu University"))
STATE_SHORT = {"up", "hp", "mp", "wb", "ap", "tn", "jk", "uk", "cg", "ka", "kl", "mh", "rj", "gj", "pb", "hr", "br", "od"}
# Words that say what kind of place it is: these must agree ("Dental" is never "Medical").
KINDS = {"medical", "dental", "nursing", "engineering", "technology", "pharmacy", "ayurveda", "ayurvedic", "homoeopathy",
         "homoeopathic", "homeopathic", "unani", "siddha", "physiotherapy", "architecture", "law", "agriculture",
         "veterinary", "information", "design", "management", "handloom"}
GENERIC = {"government", "rajkiya", "college", "colleges", "hospital", "institute", "university", "school", "centre",
           "center", "research", "autonomous", "state", "district", "general", "sciences", "science", "education",
           "academy", "post", "graduate", "allopathic", "national", "indian", "all", "india", "central", "campus",
           "teaching", "memorial", "and", "dr", "shri", "sri", "smt", "late", "for", "women", "trust", "society"}


def _kind_and_names(text: str) -> tuple[set[str], set[str]]:
    for pattern, long in ACRONYMS:
        text = re.sub(pattern, long, text)
    text = re.sub(r"\b([A-Za-z])\.\s?([A-Za-z])\b\.?", r"\1\2", text)  # "H.P" → "HP"
    tokens = {t for t in _tokens(text) if len(t) > 1}
    _, index = geo._index()
    places = {t for t in tokens if t in index}
    return tokens & KINDS, tokens - KINDS - GENERIC - STATE_SHORT - places


def _close(a: str, b: str) -> bool:
    from difflib import SequenceMatcher

    return a == b or (min(len(a), len(b)) >= 5 and SequenceMatcher(None, a, b).ratio() >= 0.8)


def same_place_name(official: str, candidate: str) -> bool:
    """Whether an OpenStreetMap name is this college: the same kind (medical, dental…) and the
    same proper names, neither side having one the other lacks (spelling slips allowed)."""
    k1, n1 = _kind_and_names(official)
    k2, n2 = _kind_and_names(candidate)
    if k1 != k2:
        return False
    return all(any(_close(a, b) for b in n2) for a in n1) and all(any(_close(b, a) for a in n1) for b in n2)


def _names(college: College) -> list[str]:
    return [college.canonical_name, *(college.aliases or [])]


def place_ok(college: College, town: geo.Place | None, lat: float, lng: float) -> tuple[bool, str]:
    """Within 40 km of the college's town; or, with no known town, nearest a town in its state."""
    if town is not None:
        d = geo.km(lat, lng, town.lat, town.lng)
        return d <= MAX_KM, f"{d:.0f} km from {town.name}"
    places, _ = geo._index()
    nearest = min(places, key=lambda p: geo.km(lat, lng, p.lat, p.lng))
    same = geo.norm_state(nearest.state) == geo.norm_state(college.state)
    return same, f"nearest town {nearest.name}, {nearest.state}"


@dataclass
class Found:
    source: str  # overpass | nominatim
    page: Fetched
    label: str
    lat: float | None
    lng: float | None
    website: str | None = None
    founded: int | None = None
    ref: str = ""  # Q-id or osm type/id
    why: str = ""


# ---------------- Nominatim ----------------

def _variants(college: College, town: geo.Place | None) -> list[str]:
    name = re.sub(r"\(.*?\)", " ", college.canonical_name)
    core = re.sub(r"^(government|govt\.?|autonomous state)\s+", "", name.strip(), flags=re.I)
    core = core.split(",")[0].strip()
    out = [name, core]
    if town and geo.norm(town.name) not in geo.norm(core):
        out.append(f"{core} {town.name}")
    return list(dict.fromkeys(" ".join(v.split()) for v in out))


TOWN_PAGES: dict[tuple, Fetched] = {}  # one Overpass look per town per run: many colleges share a town


def around_town(fetcher: Fetcher, college: College, town: geo.Place) -> tuple[Found | None, str]:
    """Every named college, university and hospital within 30 km of the town, best name match first."""
    key = (town.name, town.lat, town.lng)
    page = TOWN_PAGES.get(key)
    if page is None:
        query = (f'[out:json][timeout:60];(nwr(around:30000,{town.lat},{town.lng})["amenity"~"^(college|university|hospital)$"]["name"];'
                 f'nwr(around:30000,{town.lat},{town.lng})["building"~"^(college|university)$"]["name"];);out center tags qt;')
        page = fetcher.get(OVERPASS, data={"data": query}, api=True)
        if page.ok:
            TOWN_PAGES[key] = page
    if not page.ok:
        return None, f"Overpass failed ({page.error})"
    best = None
    for e in json.loads(page.body).get("elements", []):
        tags = e.get("tags", {})
        point = (e.get("lat"), e.get("lon")) if "lat" in e else ((e.get("center") or {}).get("lat"), (e.get("center") or {}).get("lon"))
        if point[0] is None:
            continue
        for label in {tags.get("name"), tags.get("name:en"), tags.get("official_name"), tags.get("alt_name")} - {None}:
            if not any(same_place_name(mine, label) for mine in _names(college)):
                continue
            score = max(similarity(label, mine) for mine in _names(college))
            if best is None or score > best[0]:
                d = geo.km(point[0], point[1], town.lat, town.lng)
                best = (score, Found("overpass", page, label, point[0], point[1], tags.get("website") or tags.get("contact:website"),
                                     None, f"{e['type']}/{e['id']}", f"{d:.0f} km from {town.name}"))
    return (best[1], "") if best else (None, f"no college of that name within 30 km of {town.name} on OpenStreetMap")


def nominatim(fetcher: Fetcher, college: College, town: geo.Place | None) -> tuple[Found | None, str]:
    why = "not found on OpenStreetMap"
    for q in _variants(college, town):
        page = fetcher.get(NOMINATIM, params={"q": q, "format": "jsonv2", "limit": "3", "countrycodes": "in",
                                              "extratags": "1"}, api=True)
        if not page.ok:
            return None, f"Nominatim failed ({page.error})"
        for hit in json.loads(page.body or b"[]"):
            label = hit.get("name") or hit.get("display_name", "").split(",")[0]
            if not any(same_place_name(mine, label) for mine in _names(college)):
                continue
            lat, lng = float(hit["lat"]), float(hit["lon"])
            ok, where = place_ok(college, town, lat, lng)
            if not ok:
                why = f"OpenStreetMap's {label} is {where}"
                continue
            return Found("nominatim", page, label, lat, lng, (hit.get("extratags") or {}).get("website"), None,
                         f"{hit['osm_type']}/{hit['osm_id']}", where), ""
    return None, why


# ---------------- Overpass ----------------

def overpass_query(lat: float, lng: float) -> str:
    parts = [f'nwr(around:{radius},{lat},{lng}){f};' for radius, filters in NEAR.values() for f in filters]
    return f"[out:json][timeout:60];({''.join(parts)});out center tags qt;"


def nearest(elements: list[dict], lat: float, lng: float) -> dict[str, tuple[str, float, str] | None]:
    out: dict[str, tuple[str, float, str] | None] = {attribute: None for attribute in NEAR}
    for e in elements:
        tags = e.get("tags", {})
        point = (e.get("lat"), e.get("lon")) if "lat" in e else ((e.get("center") or {}).get("lat"), (e.get("center") or {}).get("lon"))
        if point[0] is None:
            continue
        name = tags.get("name:en") or tags.get("name")
        if not name and tags.get("amenity") not in ("atm", "pharmacy"):
            continue
        kinds = []
        if tags.get("railway") == "station" and tags.get("station") not in ("subway", "light_rail", "monorail"):
            kinds.append("near.railway_station")
        if tags.get("aeroway") == "aerodrome" and tags.get("iata"):
            kinds.append("near.airport")
        kinds += [a for a, t in (("near.hospital", "hospital"), ("near.bus_stand", "bus_station"),
                                 ("near.pharmacy", "pharmacy"), ("near.atm", "atm")) if tags.get("amenity") == t]
        d = round(geo.km(lat, lng, point[0], point[1]), 1)
        for kind in kinds:
            if d * 1000 <= NEAR[kind][0] and (out[kind] is None or d < out[kind][1]):
                label = name or ("ATM" if kind == "near.atm" else "Pharmacy")
                if kind == "near.atm" and tags.get("operator"):
                    label = f"{tags['operator']} ATM"
                out[kind] = (label, d, f"{e['type']}/{e['id']}")
    return out


# ---------------- putting it together ----------------

OSM = ("openstreetmap", "OpenStreetMap contributors (ODbL)", 5)


def _doc(publisher: tuple, page: Fetched, title: str) -> Document:
    return Document(publisher[0], publisher[1], publisher[2], page.final_url, title, page.retrieved_at,
                    sha256=page.sha256, parse="text")


def values_for(fetcher: Fetcher, college: College) -> tuple[list[Value], str]:
    town = geo.town_of(college.city, college.state, college.canonical_name)
    found, why = around_town(fetcher, college, town) if town else (None, "town not known")
    if found is None:
        found, why_osm = nominatim(fetcher, college, town)
        why = f"{why}; {why_osm}" if found is None else ""
    if found is None:
        return [], why
    at = found.page.retrieved_at
    doc = _doc(OSM, found.page, f"OpenStreetMap: {found.label} ({found.ref})")
    gen = "maya-locations/1"
    vals = [Value("location.coordinates", {"lat": round(found.lat, 6), "lng": round(found.lng, 6)}, doc,
                  locator=f"{found.ref}; {found.why}", quote=f"{found.label}: {found.lat:.6f}, {found.lng:.6f}",
                  generated_by=gen, at=at)]
    if found.website:
        vals.append(Value("location.website", {"url": found.website}, doc, locator=found.ref,
                          quote=f"website={found.website}", generated_by=gen, at=at))
    page = fetcher.get(OVERPASS, data={"data": overpass_query(found.lat, found.lng)}, api=True)
    if page.ok:
        doc = _doc(OSM, page, f"OpenStreetMap places near {college.canonical_name}")
        for attribute, hit in nearest(json.loads(page.body).get("elements", []), found.lat, found.lng).items():
            radius = NEAR[attribute][0] // 1000
            if hit is None:
                vals.append(Value(attribute, None, doc, locator=f"none within {radius} km on OpenStreetMap",
                                  generated_by="maya-locations/1", at=page.retrieved_at))
            else:
                name, d, ref = hit
                vals.append(Value(attribute, {"name": name, "km": d, "kind": "straight_line"}, doc,
                                  locator=f"{ref}, searched within {radius} km", quote=f"{name}: {d} km",
                                  generated_by="maya-locations/1", at=page.retrieved_at))
    return vals, "" if page.ok else f"nearby places: {page.error}"


def run(db: Session, fetcher: Fetcher, root=None, limit: int | None = None, refresh: bool = False,
        batch: int = 25, progress=print) -> dict:
    TOWN_PAGES.clear()
    colleges = list(db.execute(select(College).order_by(College.id)).scalars())
    if not refresh:
        colleges = [c for c in colleges if "location.coordinates" not in store.current(db, "college", c.id,
                                                                                      attributes=["location.coordinates"])]
    colleges = colleges[:limit] if limit else colleges
    report = {"placed": 0, "unplaced": [], "notes": [], "commits": 0}
    pending: dict = {}
    for n, college in enumerate(colleges, start=1):
        vals, why = values_for(fetcher, college)
        if vals:
            pending[college_entity(college)] = vals
            report["placed"] += 1
        else:
            report["unplaced"].append(f"{college.canonical_name}: {why}")
        if why and vals:
            report["notes"].append(f"{college.canonical_name}: {why}")
        if len(pending) >= batch or (n == len(colleges) and pending):
            result = publish(db, pending, f"Locations and nearby places for {len(pending)} colleges "
                                          f"({datetime.now(timezone.utc):%Y-%m-%d})", root)
            report["commits"] += 1
            report.setdefault("problems", []).extend(result["problems"])
            pending = {}
            progress(f"{n}/{len(colleges)}: {report['placed']} placed, {len(report['unplaced'])} not")
    return report


if __name__ == "__main__":
    from app.core.config import get_settings
    from app.core.db import SessionLocal

    args = sys.argv[1:]
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    with SessionLocal() as session, Fetcher(get_settings().source_store_path) as fetcher:
        result = run(session, fetcher, limit=limit, refresh="--refresh" in args, progress=lambda m: print(m, flush=True))
    print("placed:", result["placed"], "| commits:", result["commits"], "| problems:", result.get("problems", [])[:10])
    print("not placed:", len(result["unplaced"]), *result["unplaced"], sep="\n  ")
    print("notes:", *result["notes"][:50], sep="\n  ")
