"""Turns a college's researched profile and real cutoffs into short lines a student can read
(and MAYA can say): ranking, how hard it is to get in, cost, placements, surroundings.

Shared by the Compare page and the college page so both say things the same way.
"""

from __future__ import annotations

import re

EXAM_RANK = {
    "JEE_ADVANCED": "JEE Advanced rank",
    "JEE_MAIN": "JEE Main rank",
    "NEET_UG": "NEET All-India Rank",
}
QUOTA_POOL = {
    "AI": "all-India seats", "OS": "other-state seats", "HS": "home-state seats",
    "AIQ": "All-India Quota seats", "Open": "open seats", "Deemed": "deemed-university seats",
    "Delhi": "Delhi-quota seats", "Puducherry": "Puducherry-quota seats",
    "GO": "Goa-quota seats", "JK": "J&K-quota seats", "LA": "Ladakh-quota seats",
}
SHORT_NAMES = [
    (r"^Indian Institute of Technology\s*", "IIT "),
    (r"^National Institute of Technology Karnataka,?\s*", "NIT Karnataka, "),
    (r"^National Institute of Technology,?\s*", "NIT "),
    (r"^Indian Institute of Information Technology,?\s*", "IIIT "),
    (r"^Maulana Azad Medical College", "MAMC"),
    (r"^Vardhman Mahavir Medical College & Safdarjung Hospital", "VMMC & Safdarjung"),
]


def short_name(name: str) -> str:
    for pattern, replacement in SHORT_NAMES:
        new = re.sub(pattern, replacement, name)
        if new != name:
            return new.strip()
    return name


def lakh(amount: float | int | None) -> str:
    if amount is None:
        return "not known"
    if amount >= 100000:
        value = amount / 100000
        return f"₹{value:.2f}".rstrip("0").rstrip(".") + " lakh"
    return f"₹{amount:,.0f}"


def ranking_line(profile: dict | None) -> str | None:
    nirf = (profile or {}).get("nirf")
    if not nirf:
        return None
    return f"NIRF {nirf['year']} {nirf['category']}: #{nirf['rank']} in India"


def admission_lines(admission: dict | None) -> list[str]:
    if not admission:
        return ["No official cutoff loaded for this college yet."]
    rank = EXAM_RANK.get(admission["exam_code"], "rank")
    pool = QUOTA_POOL.get(admission["toughest"]["quota"], "open seats")
    lines = [f"{admission['year']} closing ranks, round {admission['round']} — open category, {pool}, by {rank}:"]
    toughest, easiest = admission["toughest"], admission["easiest"]
    if admission["program_count"] == 1:
        lines.append(f"{toughest['program']}: closed at {toughest['closing_rank']:,}")
    else:
        lines.append(f"Hardest: {toughest['program']} — closed at {toughest['closing_rank']:,}")
        lines.append(f"Easiest: {easiest['program']} — closed at {easiest['closing_rank']:,}")
        lines.append(f"{admission['program_count']} programs in all")
    return lines


def fee_lines(profile: dict | None) -> list[str]:
    fees = (profile or {}).get("fees")
    if not fees:
        return []
    lines = [fees["summary"]]
    if fees.get("living"):
        lines.append(fees["living"])
    if fees.get("waivers"):
        lines.append(fees["waivers"])
    return lines


def placement_lines(profile: dict | None) -> list[str]:
    p = (profile or {}).get("placements")
    if not p:
        return []
    if p.get("note") and p.get("median_lpa") is None:
        return [p["note"]]
    lines = []
    if p.get("median_lpa") is not None:
        lines.append(f"Median package: ₹{p['median_lpa']:g} lakh a year")
    if p.get("average_lpa") is not None:
        lines.append(f"Average package: ₹{p['average_lpa']:g} lakh a year")
    if p.get("highest"):
        lines.append(f"Highest offer: {p['highest']}")
    if p.get("period"):
        lines.append(f"Graduating batch {p['period']}")
    return lines


def surroundings_lines(profile: dict | None) -> list[tuple[str, str]]:
    s = (profile or {}).get("surroundings") or {}
    labels = [("area", "Where"), ("airport", "Airport"), ("railway", "Railway"),
              ("local_transport", "Getting around"), ("daily_needs", "Daily needs")]
    return [(label, s[key]) for key, label in labels if s.get(key)]


def not_researched(name: str) -> str:
    return (f"MAYA hasn't researched fees, placements and surroundings for {short_name(name)} yet — "
            "check its official website. Cutoffs shown are official.")


def spoken(text: str) -> str:
    """Make figures sound right when read aloud."""
    return (text.replace("₹", "rupees ").replace("#", "number ").replace(" km", " kilometres")
            .replace("—", ",").replace("–", " to "))
