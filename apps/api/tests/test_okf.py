"""The OKF bundle: written conformant to OKF v0.2, loaded into facts, reviewed in the bundle, and
loaded again incrementally from its git history."""

from datetime import date, datetime, timedelta, timezone

from app.facts import store
from app.models.facts import Fact, OkfLoad
from app.okf import bundle, loader
from app.okf.facts import Document, Entity, Value, decide, upsert
from tests.test_facts import college

T0 = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
TODAY = date(2026, 10, 2)
MANIT = Entity("college", "Maulana Azad National Institute of Technology Bhopal", "Madhya Pradesh", "Bhopal", "NIT",
               ("MANIT", "MANIT Bhopal"))
FEES = Document("college-manit-bhopal", "MANIT Bhopal (official website)", 2, "https://www.manit.ac.in/fees-2026-27.pdf",
                "B.Tech fee structure 2026-27", T0, sha256="a" * 64, parse="text")
JOSAA = Document("josaa", "JoSAA", 3, "https://josaa.nic.in/manit.pdf", "JoSAA 2026 institute profile: MANIT", T0,
                 sha256="b" * 64, parse="text")
OSM = Document("osm", "OpenStreetMap", 5, "https://overpass-api.de/api/interpreter?manit", "OpenStreetMap, Overpass query", T0,
               sha256="c" * 64, parse="text")


def money(n):
    return {"amount": n, "per": "year", "applies_to": "general"}


def fees(**extra):
    return [Value("fee.tuition.annual", money(125000), FEES, "2026-27", locator="page 2",
                  quote="Tuition Fee (per semester) 62,500", generated_by="maya-extractor/gemini-2.5-flash", at=T0, **extra),
            Value("fee.hostel.annual", money(42000), FEES, "2026-27", locator="page 2", quote="Hostel rent 21,000 per semester",
                  generated_by="maya-extractor/gemini-2.5-flash", at=T0)]


def test_the_bundle_is_conformant_okf(tmp_path):
    log = upsert(tmp_path, MANIT, fees() + [
        Value("near.airport", {"name": "Raja Bhoj Airport", "km": 12.4, "kind": "straight_line"}, OSM,
              generated_by="maya-locations/1", verified_by="process:maya-osm", at=T0)])
    bundle.write_indexes(tmp_path, {"colleges": "Colleges, one folder each"})
    bundle.append_log(tmp_path, log, TODAY)
    assert bundle.check(tmp_path) == []
    folder = "colleges/maulana-azad-national-institute-of-technology-bhopal"
    assert {c.id.rsplit("/", 1)[-1] for c in bundle.concepts(tmp_path)} == {"college", "fees-2026-27", "location"}
    fee = bundle.read(tmp_path, f"{folder}/fees-2026-27")
    meta = fee.meta
    assert meta["type"] == "Fee Structure" and meta["status"] == "stable"
    assert meta["generated"]["by"] == "maya-extractor/gemini-2.5-flash"
    assert meta["verified"] == [{"by": "process:maya-quote-check", "at": "2026-10-02T10:00:00Z"}], "machine-confirmed"
    assert meta["stale_after"] == "2027-08-01T00:00:00Z", "2026-27 fees go stale when the 2027-28 cycle starts"
    assert meta["sources"] == [{"id": "s1", "resource": FEES.url, "title": FEES.title, "author": "org:college-manit-bhopal",
                                "publisher": FEES.publisher, "tier": 2, "retrieved_at": "2026-10-02T10:00:00Z",
                                "sha256": "a" * 64, "parse": "text"}]
    assert "| Tuition fee | ₹1,25,000 a year | 2026-27 | checked | [^s1] |" in fee.body
    assert "[^s1]: B.Tech fee structure 2026-27, MANIT Bhopal (official website) (retrieved 2026-10-02)" in fee.body
    identity = bundle.read(tmp_path, f"{folder}/college").meta
    assert identity["type"] == "College" and identity["description"] == "NIT in Bhopal, Madhya Pradesh."
    assert identity["maya"]["entity"]["aliases"] == ["MANIT", "MANIT Bhopal"]
    assert (tmp_path / "index.md").read_text().startswith('---\nokf_version: "0.2"\n---')
    assert "* [Maulana Azad National Institute of Technology Bhopal — fees 2026-27](fees-2026-27.md)" in \
        (tmp_path / folder / "index.md").read_text()
    assert "## 2026-10-02" in (tmp_path / "log.md").read_text()
    again = bundle.render(fee)
    assert bundle.render(bundle.parse(again, fee.id)) == again, "the same content gives the same bytes"


def test_the_same_publisher_replaces_its_value(tmp_path):
    upsert(tmp_path, MANIT, fees())
    newer = Document(FEES.publisher_key, FEES.publisher, 2, FEES.url, FEES.title, T0 + timedelta(days=30), sha256="d" * 64,
                     parse="text")
    log = upsert(tmp_path, MANIT, [Value("fee.hostel.annual", money(45000), newer, "2026-27", at=T0 + timedelta(days=30))])
    assert log == ["**Update**: Hostel fee for [Maulana Azad National Institute of Technology Bhopal]"
                   "(/colleges/maulana-azad-national-institute-of-technology-bhopal/fees-2026-27.md) changed from "
                   "₹42,000 a year to ₹45,000 a year (verified, from B.Tech fee structure 2026-27)"]
    fee = bundle.read(tmp_path, "colleges/maulana-azad-national-institute-of-technology-bhopal/fees-2026-27")
    assert [f["value"]["amount"] for f in fee.meta["maya"]["facts"]] == [125000, 45000]
    assert len(fee.meta["sources"]) == 2, "each value cites the version of the document it came from"
    assert upsert(tmp_path, MANIT, [Value("fee.hostel.annual", money(45000), newer, "2026-27", at=T0 + timedelta(days=31))]) == []


def test_loading_fills_facts_and_a_review_in_the_bundle_reaches_them(tmp_path, db_session):
    manit = college(db_session)
    upsert(tmp_path, MANIT, fees() + [
        Value("fee.one_time", money(5), FEES, "2026-27", flags=["₹5 is below the expected range"], at=T0)])
    run = loader.load(db_session, tmp_path)
    assert run.problems == [] and run.facts == 3
    shown = store.current(db_session, "college", manit.id, today=TODAY)
    assert shown["fee.tuition.annual"]["value"]["amount"] == 125000
    assert shown["fee.tuition.annual"]["quote"] == "Tuition Fee (per semester) 62,500"
    assert shown["fee.tuition.annual"]["source"]["name"] == "MANIT Bhopal (official website)"
    assert "fee.one_time" not in shown, "flagged: waiting for review"
    count = db_session.query(Fact).count()
    loader.load(db_session, tmp_path, everything=True)
    assert db_session.query(Fact).count() == count, "loading again changes nothing"

    cid = "colleges/maulana-azad-national-institute-of-technology-bhopal/fees-2026-27"
    decide(tmp_path, cid, "fee.one_time", "2026-27", "s1", "edit", "dhruv", note="₹5,000, misread", value=money(5000))
    decide(tmp_path, cid, "fee.hostel.annual", "2026-27", "s1", "reject", "dhruv", note="that's the rent for one semester")
    loader.load(db_session, tmp_path, everything=True)
    shown = store.current(db_session, "college", manit.id, today=TODAY)
    assert shown["fee.one_time"]["value"]["amount"] == 5000 and shown["fee.one_time"]["verified_by"] == "human"
    assert "fee.hostel.annual" not in shown, "rejected in the bundle → withdrawn"
    entry = next(f for f in bundle.read(tmp_path, cid).meta["maya"]["facts"] if f["attribute"] == "fee.one_time")
    assert entry["verified"] == [{"by": "human:dhruv", "at": entry["verified"][0]["at"]}], "OKF: human-reviewed"


def test_a_conflict_is_written_out_and_settled_in_the_bundle(tmp_path, db_session):
    manit = college(db_session)
    upsert(tmp_path, MANIT, fees() + [Value("fee.hostel.annual", money(38000), JOSAA, "2026-27", at=T0)])
    cid = "colleges/maulana-azad-national-institute-of-technology-bhopal/fees-2026-27"
    body = bundle.read(tmp_path, cid).body
    assert "# Conflicts" in body and "Hostel fee (2026-27): [^s1] says ₹42,000 a year; [^s2] says ₹38,000 a year" in body
    loader.load(db_session, tmp_path)
    assert store.current(db_session, "college", manit.id, today=TODAY)["fee.hostel.annual"]["status"] == "conflicted"
    decide(tmp_path, cid, "fee.hostel.annual", "2026-27", "s1", "pick", "dhruv", note="the institute's own notice")
    loader.load(db_session, tmp_path, everything=True)
    shown = store.current(db_session, "college", manit.id, today=TODAY)["fee.hostel.annual"]
    assert shown["status"] == "verified" and shown["value"]["amount"] == 42000 and shown["conflict"] is None


def test_loading_follows_the_bundle_history(tmp_path, db_session):
    manit = college(db_session)
    bundle.ensure_repo(tmp_path)
    upsert(tmp_path, MANIT, fees() + [Value("near.airport", {"name": "Raja Bhoj Airport", "km": 12.4}, OSM, at=T0)])
    bundle.commit(tmp_path, "first read")
    first = loader.load(db_session, tmp_path)
    assert first.commit == bundle.head(tmp_path) and first.concepts == 3
    upsert(tmp_path, MANIT, [Value("near.airport", {"name": "Raja Bhoj Airport", "km": 12.6}, OSM, at=T0 + timedelta(days=1))])
    bundle.commit(tmp_path, "OSM again")
    second = loader.load(db_session, tmp_path)
    assert second.concepts == 1, "only what changed is read"
    assert store.current(db_session, "college", manit.id, today=TODAY)["near.airport"]["value"]["km"] == 12.6
    bundle.path_of(tmp_path, "colleges/maulana-azad-national-institute-of-technology-bhopal/location").unlink()
    bundle.commit(tmp_path, "location removed")
    loader.load(db_session, tmp_path)
    assert "near.airport" not in store.current(db_session, "college", manit.id, today=TODAY)
    assert db_session.query(OkfLoad).count() == 3


def test_what_the_loader_tolerates_and_reports(tmp_path, db_session):
    college(db_session)
    upsert(tmp_path, Entity("college", "Institute That Isn't In The Data"), fees())
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "about.md").write_text("---\ntype: Reference\ntitle: About this bundle\n---\n\nWritten by hand.\n")
    (tmp_path / "notes" / "broken.md").write_text("no frontmatter here\n")
    run = loader.load(db_session, tmp_path)
    assert "notes/broken.md" not in str(run.problems) and "notes/broken: no frontmatter" in run.problems
    assert any("no college called" in p and "Institute That Isn't In The Data" in p for p in run.problems)
    assert run.facts == 0, "a concept MAYA didn't write is read, not rejected"
