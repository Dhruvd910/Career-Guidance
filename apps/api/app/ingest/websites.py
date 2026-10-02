"""Official websites, confirmed by the sites themselves (docs/design/15-phase6-plan.md, Step 4).

Candidates come from OpenStreetMap's website tags and, for the national institutes, a list of
their known domains. A candidate counts only when its own home page names the institute — in its
title or opening lines — and then the site itself is the source (tier 2), its title the quote.
A candidate that doesn't load, or doesn't say whose site it is, is reported, never recorded.

    python -m app.ingest.websites
"""

from __future__ import annotations

import sys
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.facts import store
from app.ingest.crawl import title_names
from app.ingest.fetch import Fetcher
from app.ingest.locations import NATIONAL
from app.ingest.publish import college_entity, publish
from app.ingest.text import extract
from app.models.college import College
from app.okf.facts import Document, Value, slug

# Known domains of the national institutes — guesses until each site confirms itself.
DOMAINS = {
    "IIT Bhilai": "iitbhilai.ac.in", "IIT Bhubaneswar": "iitbbs.ac.in", "IIT BHU": "iitbhu.ac.in", "IIT Bombay": "iitb.ac.in",
    "IIT Delhi": "home.iitd.ac.in", "IIT Dharwad": "iitdh.ac.in", "IIT Gandhinagar": "iitgn.ac.in", "IIT Goa": "iitgoa.ac.in",
    "IIT Guwahati": "iitg.ac.in", "IIT Hyderabad": "iith.ac.in", "IIT Indore": "iiti.ac.in", "IIT ISM": "iitism.ac.in",
    "IIT Jammu": "iitjammu.ac.in", "IIT Jodhpur": "iitj.ac.in", "IIT Kanpur": "iitk.ac.in", "IIT Kharagpur": "iitkgp.ac.in",
    "IIT Madras": "iitm.ac.in", "IIT Mandi": "iitmandi.ac.in", "IIT Palakkad": "iitpkd.ac.in", "IIT Patna": "iitp.ac.in",
    "IIT Roorkee": "iitr.ac.in", "IIT Ropar": "iitrpr.ac.in", "IIT Tirupati": "iittp.ac.in",
    "NITJ": "nitj.ac.in", "MNIT": "mnit.ac.in", "MANIT": "manit.ac.in", "MNNIT": "mnnit.ac.in", "NIT Agartala": "nita.ac.in",
    "NIT Andhra Pradesh": "nitandhra.ac.in", "NIT Arunachal Pradesh": "nitap.ac.in", "NIT Calicut": "nitc.ac.in",
    "NIT Delhi": "nitdelhi.ac.in", "NIT Durgapur": "nitdgp.ac.in", "NIT Goa": "nitgoa.ac.in", "NIT Hamirpur": "nith.ac.in",
    "NIT Jamshedpur": "nitjsr.ac.in", "NITK": "nitk.ac.in", "NIT Kurukshetra": "nitkkr.ac.in", "NIT Manipur": "nitmanipur.ac.in",
    "NIT Meghalaya": "nitm.ac.in", "NIT Mizoram": "nitmz.ac.in", "NIT Nagaland": "nitnagaland.ac.in", "NIT Patna": "nitp.ac.in",
    "NIT Puducherry": "nitpy.ac.in", "NIT Raipur": "nitrr.ac.in", "NITR": "nitrkl.ac.in", "NIT Sikkim": "nitsikkim.ac.in",
    "NIT Silchar": "nits.ac.in", "NIT Srinagar": "nitsri.ac.in", "NIT Trichy": "nitt.edu", "NIT Uttarakhand": "nituk.ac.in",
    "NITW": "nitw.ac.in", "SVNIT": "svnit.ac.in", "VNIT": "vnit.ac.in",
    "IIITM Gwalior": "iiitm.ac.in", "IIIT Agartala": "iiitagartala.ac.in", "IIIT Allahabad": "iiita.ac.in",
    "IIIT Bhagalpur": "iiitbh.ac.in", "IIIT Bhopal": "iiitbhopal.ac.in", "IIITDM Kancheepuram": "iiitdm.ac.in",
    "IIIT Guwahati": "iiitg.ac.in", "IIIT Dharwad": "iiitdwd.ac.in", "IIIT Kalyani": "iiitkalyani.ac.in",
    "IIIT Kota": "iiitkota.ac.in", "IIIT Kottayam": "iiitkottayam.ac.in", "IIIT Nagpur": "iiitn.ac.in", "IIIT Pune": "iiitp.ac.in",
    "IIIT Ranchi": "iiitranchi.ac.in", "IIIT Una": "iiitu.ac.in", "IIIT Vadodara": "iiitvadodara.ac.in", "IIIT Lucknow": "iiitl.ac.in",
    "IIIT Raichur": "iiitr.ac.in", "IIIT Surat": "iiitsurat.ac.in", "IIIT Tiruchirappalli": "iiitt.ac.in",
    "IIITDM Jabalpur": "iiitdmj.ac.in", "IIIT Sonepat": "iiitsonepat.ac.in",
    "AIIMS Delhi": "aiims.edu", "AIIMS Bhopal": "aiimsbhopal.edu.in", "AIIMS Bhubaneswar": "aiimsbhubaneswar.nic.in",
    "AIIMS Jodhpur": "aiimsjodhpur.edu.in", "AIIMS Patna": "aiimspatna.edu.in", "AIIMS Raipur": "aiimsraipur.edu.in",
    "AIIMS Rishikesh": "aiimsrishikesh.edu.in", "AIIMS Nagpur": "aiimsnagpur.edu.in", "AIIMS Mangalagiri": "aiimsmangalagiri.edu.in",
    "AIIMS Gorakhpur": "aiimsgorakhpur.edu.in", "AIIMS Kalyani": "aiimskalyani.edu.in", "AIIMS Rajkot": "aiimsrajkot.edu.in",
    "AIIMS Bathinda": "aiimsbathinda.edu.in", "AIIMS Guwahati": "aiimsguwahati.ac.in", "AIIMS Jammu": "aiimsjammu.edu.in",
    "AIIMS Madurai": "aiimsmadurai.edu.in", "AIIMS Deogarh": "aiimsdeoghar.edu.in", "AIIMS Rai Bareli": "aiimsrbl.edu.in",
    "AIIMS Bibi Nagar": "aiimsbibinagar.edu.in", "AIIMS Bilaspur": "aiimsbilaspur.edu.in",
    "JIPMER PUDUCHERRY": "jipmer.edu.in", "IISc": "iisc.ac.in", "IIEST": "iiests.ac.in",
}


def candidates(db: Session, college: College) -> list[str]:
    names = [college.canonical_name, *(college.aliases or [])]
    out = [f"https://www.{d}/" if d.count(".") < 3 and not d.startswith(("home.", "www.")) else f"https://{d}/"
           for key, d in DOMAINS.items() if key in names]
    osm = (store.current(db, "college", college.id, attributes=["location.website"]).get("location.website") or {})
    url = (osm.get("value") or {}).get("url") if osm.get("status") != "not_available" else None
    if url:
        out.append(url if url.startswith("http") else f"https://{url}")
    return list(dict.fromkeys(out))


def confirm(fetcher: Fetcher, college: College, url: str) -> tuple[Value | None, str]:
    page = fetcher.get(url)
    if not page.ok and url.startswith("https://www."):
        page = fetcher.get(url.replace("https://www.", "https://", 1))
    if not page.ok:
        return None, f"{url}: {page.error}"
    text = extract(page.body, page.final_url, page.mime, page.storage_path)
    line = title_names(page, text, [college.canonical_name, *(college.aliases or [])])
    if not line:
        return None, f"{url}: the page doesn't say it's {college.canonical_name} (title: {text.title[:80]!r})"
    parts = urlsplit(page.final_url)
    home = f"{parts.scheme}://{parts.netloc}/"
    doc = Document(f"site-{slug(college.canonical_name)}", f"{college.canonical_name} (official website)", 2,
                   page.final_url, text.title or home, page.retrieved_at, sha256=page.sha256, parse="text")
    return Value("location.website", {"url": home}, doc, locator="home page", quote=line[:300],
                 generated_by="maya-websites/1", at=page.retrieved_at), ""


def run(db: Session, fetcher: Fetcher, root=None, only_national: bool = True) -> dict:
    colleges = [c for c in db.execute(select(College).order_by(College.id)).scalars()
                if not only_national or c.college_type in NATIONAL]
    found, missing, values = 0, [], {}
    for college in colleges:
        why = []
        for url in candidates(db, college):
            value, problem = confirm(fetcher, college, url)
            if value:
                values[college_entity(college)] = [value]
                found += 1
                break
            why.append(problem)
        else:
            missing.append(f"{college.canonical_name}: " + ("; ".join(why) or "no candidate address"))
    report = {"confirmed": found, "missing": missing}
    if values:
        report.update(publish(db, values, f"Official websites confirmed by their own home pages ({found})", root))
    return report


if __name__ == "__main__":
    from app.core.config import get_settings
    from app.core.db import SessionLocal

    with SessionLocal() as session, Fetcher(get_settings().source_store_path) as fetcher:
        result = run(session, fetcher, only_national="--all" not in sys.argv)
    print("confirmed:", result["confirmed"], "| commit:", result.get("commit"), "| problems:", result.get("problems", [])[:5])
    print("not confirmed:", len(result["missing"]), *result["missing"], sep="\n  ")
