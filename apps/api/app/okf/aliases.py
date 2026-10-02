"""The short names students use for colleges — "NIT Trichy", "MANIT", "IIT BHU" — so search
finds them. Patterns cover the standard official names; well-known acronyms are listed by hand.
They're written into each college's identity concept in the OKF bundle (maya.entity.aliases),
where they can be reviewed like any other knowledge."""

from __future__ import annotations

import re

PATTERNS = (
    (r"National Institute of Technology", "NIT"),
    (r"Indian Institute of Technology", "IIT"),
    (r"Indian Institute of Information Technology", "IIIT"),
    (r"All India Institute of Medical Sciences", "AIIMS"),
)
CURATED = (
    (r"^Maulana Azad National Institute of Technology", ["MANIT", "MANIT Bhopal", "NIT Bhopal"]),
    (r"^Motilal Nehru National Institute of Technology", ["MNNIT", "MNNIT Allahabad", "NIT Allahabad", "NIT Prayagraj"]),
    (r"^Malaviya National Institute of Technology", ["MNIT", "MNIT Jaipur", "NIT Jaipur"]),
    (r"^Visvesvaraya National Institute of Technology", ["VNIT", "VNIT Nagpur", "NIT Nagpur"]),
    (r"^Sardar Vallabhbhai National Institute of Technology", ["SVNIT", "SVNIT Surat", "NIT Surat"]),
    (r"^Dr\.? B ?R Ambedkar National Institute of Technology", ["NIT Jalandhar", "NITJ"]),
    (r"National Institute of Technology,? Tiruchirappalli", ["NIT Trichy", "NITT"]),
    (r"National Institute of Technology Karnataka", ["NITK", "NIT Surathkal", "NITK Surathkal"]),
    (r"National Institute of Technology,? Rourkela", ["NITR"]),
    (r"National Institute of Technology,? Warangal", ["NITW"]),
    (r"National Institute of Technology,? Calicut", ["NITC"]),
    (r"Indian Institute of Technology \(BHU\)", ["IIT BHU", "IIT Varanasi", "IIT (BHU)"]),
    (r"Indian Institute of Technology \((ISM|Indian School of Mines)\)", ["IIT ISM", "IIT Dhanbad", "ISM Dhanbad"]),
    (r"^Jawaharlal Institute of Post ?Graduate Medical Education", ["JIPMER", "JIPMER Puducherry"]),
    (r"^Atal Bihari Vajpayee Indian Institute of Information Technology", ["ABV-IIITM", "IIITM Gwalior", "IIIT Gwalior"]),
    (r"^Pt\.? Dwarka Prasad Mishra Indian Institute of Information Technology", ["IIITDM Jabalpur", "IIIT Jabalpur"]),
    (r"^Indian Institute of Engineering Science and Technology", ["IIEST", "IIEST Shibpur", "BESU Shibpur"]),
    (r"^Indian Institute of Science\b", ["IISc", "IISc Bangalore", "IISc Bengaluru"]),
    (r"^Indian Institute of Information Technology,? Design (and|&) Manufacturing,? Kancheepuram", ["IIITDM Kancheepuram"]),
    (r"^AIIMS[-, ]+New Delhi|All India Institute of Medical Sciences,? New Delhi", ["AIIMS Delhi"]),
)


def _tidy(text: str) -> str:
    text = re.sub(r"\(.*?\)", " ", text)
    return " ".join(text.replace(",", " ").split())


def aliases_for(name: str, city: str | None = None) -> list[str]:
    out: list[str] = []
    plain = _tidy(name)
    for long, short in PATTERNS:
        m = re.search(rf"\b{long}\b[ ,]*(.*)$", plain, re.I)
        if m and m.group(1):
            place = m.group(1).split("  ")[0]
            first = place.split(" ")[0] if len(place.split(" ")) > 2 else place
            out += [f"{short} {place}", f"{short} {first}"]
            if city:
                out.append(f"{short} {city.title() if city.isupper() else city}")
    m = re.match(r"^(AIIMS|JIPMER)[-, ]+(.+)$", name, re.I)
    if m:
        out.append(f"{m.group(1).upper()} {m.group(2).strip().title()}")
    for pattern, names in CURATED:
        if re.search(pattern, name, re.I):
            out += names
    seen, result = {name.lower()}, []
    for a in out:
        a = " ".join(a.split())
        if a and a.lower() not in seen:
            seen.add(a.lower())
            result.append(a)
    return result
