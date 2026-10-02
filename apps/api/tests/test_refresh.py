"""'Check for updates' and the nightly refresh: asked-for colleges first, weekly documents only when
a week has passed, and model reading stopped at the night's budget. The jobs themselves are faked."""

from datetime import datetime, timedelta, timezone

from app.facts import store
from app.ingest import college_facts, refresh
from app.models.facts import RefreshRequest
from tests.test_college_facts import manit


def test_asking_twice_queues_once(client, db_session):
    college = manit(db_session)
    db_session.commit()
    first = client.post(f"/api/colleges/{college.id}/refresh").json()
    client.post(f"/api/colleges/{college.id}/refresh")
    assert first["queued"] and "tonight" in first["message"]
    assert db_session.query(RefreshRequest).filter_by(college_id=college.id).count() == 1
    assert client.post("/api/colleges/999999/refresh").status_code == 404


def test_the_nightly_refresh(tmp_path, db_session, monkeypatch):
    college = manit(db_session)
    db_session.add(RefreshRequest(college_id=college.id))
    src = store.source(db_session, "josaa", "JoSAA", 3)
    store.document(db_session, src, "https://josaa.nic.in/rules.pdf", "Business Rules 2026",
                   datetime.now(timezone.utc) - timedelta(days=2), sha256="a" * 64, parse_status="text")
    db_session.flush()
    calls = []
    monkeypatch.setattr(college_facts, "site_of", lambda db, c: "https://www.manit.ac.in/")

    def values_for(db, fetcher, c, usage, reader=None, **kw):
        calls.append(("read", c.canonical_name))
        reader(c.canonical_name, "Bhopal", "Fees", "https://www.manit.ac.in/fees.pdf", None, usage)
        return [], []

    def costly_read(*args, **kwargs):
        args[5].add({"cost": 0.20})
        return [], 0

    monkeypatch.setattr(college_facts, "values_for", values_for)
    monkeypatch.setattr(refresh.reading, "read", costly_read)
    monkeypatch.setattr(refresh.documents, "run", lambda *a, **k: calls.append("documents") or {"documents": []})
    monkeypatch.setattr(refresh.admissions, "run", lambda *a, **k: calls.append("dates") or {"dates": 0})
    monkeypatch.setattr(refresh.nirf, "run", lambda *a, **k: calls.append("nirf") or {"ranked": {}})
    monkeypatch.setattr(refresh.locations, "run", lambda *a, **k: calls.append("places") or {"placed": 0})
    report = refresh.run(db_session, fetcher=None, root=tmp_path / "okf", budget=0.25, progress=lambda m: None)
    assert calls[0] == ("read", college.canonical_name), "the college someone asked about comes first"
    assert db_session.query(RefreshRequest).one().done_at is not None
    assert "documents" not in calls and "dates" not in calls, "the documents were fetched two days ago"
    assert report["asked"] == 1 and report["fees"] == 0 and "nirf" in calls and "places" in calls
    assert 0.2 <= report["cost"] < 0.45, "reading stops once the night's budget is spent"
