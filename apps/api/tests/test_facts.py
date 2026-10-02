"""Facts with provenance: superseding, conflicts between sources, what's shown, and how fresh."""

from datetime import date, datetime, timedelta, timezone

from app.facts import freshness, store
from app.models.college import College
from app.models.facts import Fact, FactConflict

T0 = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
TODAY = date(2026, 10, 2)


def college(db, name="Maulana Azad National Institute of Technology Bhopal"):
    c = College(canonical_name=name, college_type="NIT", ownership="government", state="Madhya Pradesh",
                city="Bhopal", is_demo_data=False)
    db.add(c)
    db.flush()
    return c


def doc(db, key="manit", tier=2, url="https://www.manit.ac.in/fees.pdf", sha="a" * 64, title="MANIT fee notice 2026-27"):
    src = store.source(db, key, f"{key} publisher", tier)
    return store.document(db, src, url, title, T0, sha256=sha, parse_status="text")


def money(n):
    return {"amount": n, "per": "year", "applies_to": "general"}


def test_freshness_labels():
    ago = lambda days: T0 - timedelta(days=days)  # noqa: E731
    assert freshness.label("verified", "near.airport", T0, None, TODAY)["en"] == "Verified today"
    assert freshness.label("verified", "near.airport", ago(7), None, TODAY)["en"] == "Verified 7 days ago"
    assert freshness.label("verified", "near.airport", ago(401), None, TODAY)["state"] == "stale"
    fee = freshness.label("verified", "fee.tuition.annual", T0, "2026-27", date(2027, 8, 1))
    assert fee["en"] == "Stale — as of 2 Oct 2026", "a fee goes stale when the next admission cycle starts"
    assert freshness.label("verified", "fee.tuition.annual", T0, "2026-27", date(2027, 7, 31))["state"] == "fresh"
    assert freshness.label("unverified", "fee.tuition.annual", None, "2026-27", TODAY)["en"] == "Needs verification"
    assert freshness.label("not_available", "facility.medical", T0, None, TODAY)["en"] == "Not available (looked 2 Oct 2026)"
    assert freshness.stale_at("fee.hostel.annual", T0, "2026-27") == datetime(2027, 8, 1, tzinfo=timezone.utc)


def test_a_new_value_from_the_same_source_supersedes_and_the_same_value_reconfirms(db_session):
    manit = college(db_session)
    first = store.record(db_session, "college", manit.id, "fee.tuition.annual", money(125000), document=doc(db_session),
                         academic_year="2026-27", quote="Tuition fee 62,500 per semester", now=T0)
    again = store.record(db_session, "college", manit.id, "fee.tuition.annual", money(125000), document=doc(db_session),
                         academic_year="2026-27", now=T0 + timedelta(days=5))
    assert again.id == first.id and again.verified_at == T0 + timedelta(days=5)
    newer = doc(db_session, sha="b" * 64)
    changed = store.record(db_session, "college", manit.id, "fee.tuition.annual", money(130000), document=newer,
                           academic_year="2026-27", now=T0 + timedelta(days=9))
    assert db_session.get(Fact, first.id).superseded_by == changed.id
    shown = store.current(db_session, "college", manit.id, today=TODAY + timedelta(days=9))["fee.tuition.annual"]
    assert shown["value"]["amount"] == 130000 and shown["status"] == "verified" and shown["label"]["en"] == "Verified today"
    assert [f.value["amount"] for f in store.history(db_session, "college", manit.id, "fee.tuition.annual")] == [130000, 125000]
    assert newer.id != first.source_document_id and db_session.get(type(newer), first.source_document_id).superseded_by == newer.id


def test_official_sources_that_disagree_are_shown_as_a_conflict(db_session):
    manit = college(db_session)
    fee_notice = doc(db_session)
    brochure = doc(db_session, key="josaa", tier=3, url="https://josaa.nic.in/brochure.pdf", sha="c" * 64,
                   title="JoSAA 2026 institute brochure")
    store.record(db_session, "college", manit.id, "fee.hostel.annual", money(42000), document=fee_notice,
                 academic_year="2026-27", now=T0)
    store.record(db_session, "college", manit.id, "fee.hostel.annual", money(38000), document=brochure,
                 academic_year="2026-27", now=T0)
    shown = store.current(db_session, "college", manit.id, today=TODAY)["fee.hostel.annual"]
    assert shown["status"] == "conflicted" and shown["value"]["amount"] == 42000, "the better tier first"
    assert [c["value"]["amount"] for c in shown["conflict"]] == [38000]
    assert shown["conflict"][0]["source"]["name"] == "josaa publisher"
    store.record(db_session, "college", manit.id, "fee.hostel.annual", money(42000), document=brochure,
                 academic_year="2026-27", now=T0 + timedelta(days=1))
    assert store.current(db_session, "college", manit.id, today=TODAY)["fee.hostel.annual"]["conflict"] is None
    assert db_session.query(FactConflict).one().resolution == "agreed"


def test_a_secondary_source_never_overrides_or_disputes_an_official_one(db_session):
    manit = college(db_session)
    store.record(db_session, "college", manit.id, "fee.mess.annual", money(36000), document=doc(db_session),
                 academic_year="2026-27", now=T0)
    news = doc(db_session, key="careers360", tier=6, url="https://www.careers360.com/manit", sha=None, title="MANIT fees")
    store.record(db_session, "college", manit.id, "fee.mess.annual", money(30000), document=news,
                 academic_year="2026-27", now=T0 + timedelta(days=3))
    shown = store.current(db_session, "college", manit.id, today=TODAY)["fee.mess.annual"]
    assert shown["value"]["amount"] == 36000 and shown["conflict"] is None and shown["source"]["official"]
    assert db_session.query(FactConflict).count() == 0


def test_what_is_shown(db_session):
    manit = college(db_session)
    website = doc(db_session, url="https://www.manit.ac.in/", sha="d" * 64, title="MANIT home page")
    store.not_available(db_session, "college", manit.id, "facility.medical", document=website, now=T0)
    assert store.current(db_session, "college", manit.id, today=TODAY)["facility.medical"]["status"] == "not_available"
    nirf = doc(db_session, key="nirf", tier=1, url="https://www.nirfindia.org/manit.pdf", sha="e" * 64, title="NIRF data")
    store.record(db_session, "college", manit.id, "facility.medical", {"text": "Health centre with a doctor on call"},
                 document=nirf, now=T0)
    assert store.current(db_session, "college", manit.id, today=TODAY)["facility.medical"]["value"]["text"].startswith("Health"), \
        "a real value beats 'not available'"
    store.record(db_session, "college", manit.id, "fee.tuition.annual", money(125000), document=doc(db_session),
                 academic_year="2025-26", now=T0)
    store.record(db_session, "college", manit.id, "fee.tuition.annual", money(130000), document=doc(db_session),
                 academic_year="2026-27", now=T0)
    assert store.current(db_session, "college", manit.id, today=TODAY)["fee.tuition.annual"]["academic_year"] == "2026-27"
    store.record(db_session, "college", manit.id, "fee.one_time", money(5), document=doc(db_session),
                 academic_year="2026-27", flags=["₹5 is below the expected range"], now=T0)
    assert "fee.one_time" not in store.current(db_session, "college", manit.id, today=TODAY), "flagged values wait"
    assert [f.attribute for f in store.waiting(db_session)] == ["fee.one_time"]


def test_the_same_document_is_kept_once(db_session):
    a = doc(db_session)
    assert doc(db_session).id == a.id
    cited = doc(db_session, key="nirf", tier=1, url="https://www.nirfindia.org/r.html", sha=None, title="NIRF 2025")
    assert doc(db_session, key="nirf", tier=1, url="https://www.nirfindia.org/r.html", sha=None, title="NIRF 2025").id == cited.id


def test_a_real_value_from_any_year_beats_not_available(db_session):
    manit = college(db_session)
    template = doc(db_session, key="iit-roorkee", url="https://iitr.ac.in/fees.html", sha=None, title="IIT fees")
    store.record(db_session, "college", manit.id, "fee.tuition.annual", money(200000), document=template,
                 status="unverified", now=T0)
    store.not_available(db_session, "college", manit.id, "fee.tuition.annual", document=doc(db_session),
                        academic_year="2026-27", now=T0)
    shown = store.current(db_session, "college", manit.id, today=TODAY)["fee.tuition.annual"]
    assert shown["value"]["amount"] == 200000 and shown["label"]["en"] == "Needs verification"
