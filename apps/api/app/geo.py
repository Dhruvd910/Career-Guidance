"""Indian towns, offline — for checking where a college is, and later for "how far from home"
without a student's town ever leaving the Pi (docs/design/15-phase6-plan.md, P6-8).

The data is GeoNames' list of places with 1,000+ people, India only (CC-BY 4.0, geonames.org),
kept as app/seed/data/geonames_in.json. Rebuild it with:

    python -m app.geo build cities1000.zip admin1CodesASCII.txt
"""

from __future__ import annotations

import io
import json
import math
import re
import sys
import unicodedata
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "seed" / "data" / "geonames_in.json"
ATTRIBUTION = "Places: GeoNames (geonames.org), CC-BY 4.0"
# Old names and nicknames people still use, and recent renames GeoNames may not have yet.
TOWN_NAMES = {"trichy": "Tiruchirappalli", "calcutta": "Kolkata", "madras": "Chennai", "bangalore": "Bengaluru",
              "gurgaon": "Gurugram", "allahabad": "Prayagraj", "baroda": "Vadodara", "poona": "Pune",
              "benares": "Varanasi", "banaras": "Varanasi", "cochin": "Kochi", "trivandrum": "Thiruvananthapuram",
              "vizag": "Visakhapatnam", "mysore": "Mysuru", "mangalore": "Mangaluru", "gulbarga": "Kalaburagi",
              "belgaum": "Belagavi", "pondicherry": "Puducherry", "simla": "Shimla", "cawnpore": "Kanpur",
              "chhatrapati sambhajinagar": "Aurangabad", "dharashiv": "Osmanabad", "nava raipur": "Raipur",
              "naya raipur": "Raipur", "prayagraj": "Allahabad", "mysuru": "Mysore", "bengaluru": "Bangalore",
              "kalaburagi": "Gulbarga", "belagavi": "Belgaum", "mangaluru": "Mangalore", "gurugram": "Gurgaon"}
GENERIC = {"government", "govt", "medical", "college", "colleges", "hospital", "institute", "institutes", "sciences",
           "science", "university", "national", "technology", "research", "education", "dental", "school", "medicine",
           "state", "autonomous", "memorial", "centre", "center", "health", "nursing", "engineering", "information",
           "indian", "management", "academy", "studies", "post", "graduate", "district", "general", "city", "rural"}
STATE_NAMES = {"national capital territory of delhi": "delhi", "nct of delhi": "delhi", "orissa": "odisha",
               "pondicherry": "puducherry", "uttaranchal": "uttarakhand", "jammu and kashmir": "jammu and kashmir"}


@dataclass(frozen=True)
class Place:
    name: str
    lat: float
    lng: float
    state: str
    population: int


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower().replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def norm_state(state: str) -> str:
    s = norm(state)
    return STATE_NAMES.get(s, s)


def km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Straight-line (great-circle) distance."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(a))


@lru_cache(maxsize=1)
def _index() -> tuple[list[Place], dict[str, list[int]]]:
    rows = json.loads(DATA.read_text(encoding="utf-8"))["places"]
    places, index = [], {}
    for i, (name, lat, lng, state, population, alternates) in enumerate(rows):
        places.append(Place(name, lat, lng, state, population))
        for key in {norm(name), *(norm(a) for a in alternates)}:
            if key:
                index.setdefault(key, []).append(i)
    return places, index


def find(town: str, state: str | None = None) -> Place | None:
    """The town by name or alternate name ("Trichy", "Bombay"), preferring the given state and
    then the most populous; None when it isn't known."""
    places, index = _index()
    parts = [p.strip() for p in re.split(r"[,()]", town or "") if p.strip()]
    candidates = [town, *parts]
    candidates += [TOWN_NAMES[norm(c)] for c in list(candidates) if norm(c) in TOWN_NAMES]
    for candidate in candidates:
        hits = [places[i] for i in index.get(norm(candidate), [])]
        if state:
            in_state = [p for p in hits if norm_state(p.state) == norm_state(state)]
            hits = in_state or ([] if len(hits) > 1 else hits)
        if hits:
            return max(hits, key=lambda p: p.population)
    return None


def town_of(city: str | None, state: str | None, name: str) -> Place | None:
    """Where a college is: its listed city, or failing that (a blank city, or the state's name
    where the city should be) the town in its official name — "Government Medical College,
    Srikakulam" is in Srikakulam."""
    if city and norm(city) != norm(state or ""):
        found = find(city, state)
        if found:
            return found
    parts = [p.strip() for p in re.split(r"[,()]", name) if p.strip()]
    words = [w for part in reversed(parts) for w in re.split(r"[\s\-.]+", part) if w]
    for candidate in [*reversed(parts), *(w for w in words if len(w) > 3 and norm(w) not in GENERIC)]:
        found = find(candidate, state)
        if found and norm_state(found.state) == norm_state(state or found.state):
            return found
    return None


def build(cities_zip: str, admin1: str) -> int:
    states = {}
    for line in Path(admin1).read_text(encoding="utf-8").splitlines():
        code, name, *_ = line.split("\t")
        if code.startswith("IN."):
            states[code[3:]] = name
    rows = []
    with zipfile.ZipFile(cities_zip) as z, z.open("cities1000.txt") as f:
        for line in io.TextIOWrapper(f, encoding="utf-8"):
            cols = line.rstrip("\n").split("\t")
            if cols[8] != "IN":
                continue
            names = [a for a in cols[3].split(",") if a and len(a) < 40]
            hindi = [a for a in names if any("\u0900" <= ch <= "\u097f" for ch in a)]
            alternates = [a for a in names if a.isascii()][:10] + hindi[:4]
            rows.append([cols[1], round(float(cols[4]), 5), round(float(cols[5]), 5), states.get(cols[10], ""),
                         int(cols[14] or 0), alternates])
    rows.sort(key=lambda r: (-r[4], r[0]))
    DATA.write_text(json.dumps({"about": ATTRIBUTION, "places": rows}, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")
    _index.cache_clear()
    return len(rows)


if __name__ == "__main__" and len(sys.argv) == 4 and sys.argv[1] == "build":
    print(build(sys.argv[2], sys.argv[3]), "places")
