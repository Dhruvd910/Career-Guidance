"""Where colleges are and what's near them, from OpenStreetMap — matched strictly (a dental college
is never a medical one), checked against the town, and nearby places as straight-line distances.
Mocked responses only; never the live web."""

import json
from urllib.parse import parse_qs

import httpx

from app import geo
from app.facts import store
from app.ingest import locations
from app.ingest.fetch import Fetcher
from app.models.college import College
from tests.test_ingest_fetch import Clock


def test_towns_offline():
    assert geo.find("Trichy").name == "Tiruchirappalli" and geo.find("Bombay").name == "Mumbai"
    assert geo.find("Bhopal", "Madhya Pradesh").state == "Madhya Pradesh"
    assert geo.find("Nowhere Town") is None
    assert geo.town_of("", "Kerala", "Government Medical College, Kasaragod").name.startswith("K")
    assert geo.town_of("", "Madhya Pradesh", "AIIMS-Bhopal").name == "Bhopal"
    assert geo.town_of("Madhya Pradesh", "Madhya Pradesh", "AIIMS-Bhopal").name == "Bhopal", "a state where the city should be"
    b, i = geo.find("Bhopal"), geo.find("Indore")
    assert 165 < geo.km(b.lat, b.lng, i.lat, i.lng) < 180


def test_names_are_matched_strictly():
    m = locations.same_place_name
    assert not m("PATNA DENTAL COLLEGE & HOSPITAL, PATNA", "Patna Medical College and Hospital")
    assert not m("College of Nursing BHU, VARANASI", "Heritage College of Nursing, Varanasi")
    assert not m("Rajkiya Allopathic Medical College, Bahraich, UP", "Mahamaya Rajkiya Allopathic Medical College")
    assert m("Government Dental College, Alappuzha", "Govt Dental College Alappuzha")
    assert m("Dr. Rajendar Prasad Government Medical College, Tanda, H.P", "Dr. Rajendra Prasad Government Medical College")
    assert m("AIIMS Guwahati", "All India Institute of Medical Sciences, Guwahati")
    assert not m("AIIMS Guwahati", "Guwahati Medical College"), "an AIIMS is only ever an AIIMS"
    assert m("Maulana Azad National Institute of Technology Bhopal", "Maulana Azad National Insititute of Technology"), \
        "OpenStreetMap's own misspelling"


BHOPAL = geo.find("Bhopal", "Madhya Pradesh")
CAMPUS = {"type": "way", "id": 11, "center": {"lat": BHOPAL.lat + 0.02, "lon": BHOPAL.lng + 0.04},
          "tags": {"amenity": "college", "name": "Maulana Azad National Institute of Technology", "website": "https://www.manit.ac.in"}}
DECOY = {"type": "way", "id": 12, "center": {"lat": BHOPAL.lat, "lon": BHOPAL.lng},
         "tags": {"amenity": "college", "name": "Bhopal Dental College"}}
NEARBY = [
    {"type": "node", "id": 1, "lat": BHOPAL.lat + 0.03, "lon": BHOPAL.lng + 0.06, "tags": {"railway": "station", "name": "Rani Kamlapati"}},
    {"type": "node", "id": 2, "lat": BHOPAL.lat + 0.021, "lon": BHOPAL.lng + 0.041, "tags": {"railway": "station", "station": "subway", "name": "Metro stop"}},
    {"type": "way", "id": 3, "center": {"lat": BHOPAL.lat + 0.1, "lon": BHOPAL.lng - 0.05}, "tags": {"aeroway": "aerodrome", "iata": "BHO", "name": "Raja Bhoj Airport"}},
    {"type": "node", "id": 4, "lat": BHOPAL.lat + 0.022, "lon": BHOPAL.lng + 0.04, "tags": {"amenity": "hospital", "name": "Campus Hospital"}},
    {"type": "node", "id": 5, "lat": BHOPAL.lat + 0.03, "lon": BHOPAL.lng + 0.04, "tags": {"amenity": "hospital", "name": "Further Hospital"}},
    {"type": "node", "id": 6, "lat": BHOPAL.lat + 0.0205, "lon": BHOPAL.lng + 0.0402, "tags": {"amenity": "atm", "operator": "SBI"}},
]


def handler(request):
    if "nominatim" in request.url.host:
        return httpx.Response(200, json=[])
    query = parse_qs(request.content.decode())["data"][0]
    elements = [CAMPUS, DECOY] if "college|university|hospital" in query else NEARBY
    return httpx.Response(200, json={"elements": elements}, headers={"content-type": "application/json"})


def test_a_college_is_placed_and_its_neighbours_found(tmp_path, db_session):
    manit = College(canonical_name="Maulana Azad National Institute of Technology Bhopal", college_type="NIT",
                    ownership="government", state="Madhya Pradesh", city="Bhopal", is_demo_data=False,
                    aliases=["MANIT", "NIT Bhopal"])
    nowhere = College(canonical_name="Imaginary Dental College", college_type="Private", ownership="private",
                      state="Madhya Pradesh", city="", is_demo_data=False)
    db_session.add_all([manit, nowhere])
    db_session.flush()
    clock = Clock()
    with Fetcher(tmp_path / "sources", transport=httpx.MockTransport(handler), sleep=clock.sleep, clock=clock.time) as f:
        report = locations.run(db_session, f, root=tmp_path / "okf", progress=lambda m: None)
    assert report["placed"] == 1 and len(report["unplaced"]) == 1 and report.get("problems") == []
    assert report["unplaced"][0].startswith("Imaginary Dental College: town not known")
    shown = store.current(db_session, "college", manit.id)
    point = shown["location.coordinates"]
    assert point["value"] == {"lat": round(CAMPUS["center"]["lat"], 6), "lng": round(CAMPUS["center"]["lon"], 6)}
    assert point["source"]["name"] == "OpenStreetMap contributors (ODbL)" and point["source"]["tier"] == 5
    assert "km from Bhopal" in point["source"]["locator"]
    assert point["source"]["url"] == "https://www.openstreetmap.org/way/11", "the campus's own map page"
    assert shown["near.airport"]["source"]["url"].startswith("https://www.openstreetmap.org/?mlat="), \
        "each answer is its own document, not 'the Overpass address'"
    assert shown["location.website"]["value"] == {"url": "https://www.manit.ac.in"}
    station = shown["near.railway_station"]["value"]
    assert station["name"] == "Rani Kamlapati" and station["kind"] == "straight_line", "never the metro stop"
    assert shown["near.hospital"]["value"]["name"] == "Campus Hospital", "the nearest one"
    assert shown["near.atm"]["value"]["name"] == "SBI ATM"
    assert shown["near.pharmacy"]["status"] == "not_available"
    assert shown["near.pharmacy"]["source"]["locator"] == "none within 3 km on OpenStreetMap"
    db_session.refresh(manit)
    assert manit.latitude == point["value"]["lat"] and manit.official_website == "https://www.manit.ac.in"
    again = locations.run(db_session, Fetcher(tmp_path / "sources", transport=httpx.MockTransport(handler),
                                              sleep=clock.sleep, clock=clock.time), root=tmp_path / "okf",
                          progress=lambda m: None)
    assert again["placed"] == 0 and len(again["unplaced"]) == 1, "placed colleges aren't looked up again"
    assert json.loads(json.dumps(report))
