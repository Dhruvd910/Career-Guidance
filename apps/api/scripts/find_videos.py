"""Finds a topic-specific video for every skill — one in English, one in Hindi — and writes
app/knowledge/videos.json, which the Learn screen, career guides, roadmap steps and MAYA use.

For each skill: a YouTube search with a query written for that topic, results from a list of
trusted educational channels first (never Shorts), and each pick checked through YouTube's own
oEmbed endpoint (it must exist, with that title and channel). Nothing is made up: a skill with no
good result keeps only its search link, which the app always shows anyway.

    python scripts/find_videos.py            # all skills (about 4 minutes)
    python scripts/find_videos.py python     # one skill

Review the titles in the diff before committing: a search can surprise.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "app" / "knowledge" / "videos.json"
UA = "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

# skill → (English query, Hindi query). Written per topic: the skill's display name is often a poor search.
QUERIES = {
    "arithmetic": ("fractions decimals percentages basics", "percentage fraction decimal basic maths hindi"),
    "school_mathematics": ("algebra basics for beginners", "algebra basics class 9 maths hindi"),
    "calculus": ("calculus for beginners derivatives and integrals", "calculus basics class 12 hindi"),
    "linear_algebra": ("vectors chapter 1 essence of linear algebra", "matrices and determinants class 12 hindi"),
    "probability_statistics": ("statistics and probability full course for beginners", "probability class 12 hindi"),
    # For school students: olympiad and NTSE-style "mental ability", not bank or railway exam coaching.
    "logical_reasoning": ("logical reasoning for students olympiad", "mental ability test class 9 10 one shot hindi"),
    "problem_solving": ("problem solving for programming beginners", "how to solve coding problems hindi"),
    "physics_fundamentals": ("physics basics units and measurement motion explained", "class 11 physics basics hindi"),
    "chemistry_fundamentals": ("basic concepts of chemistry mole concept explained", "mole concept class 11 hindi"),
    "biology_fundamentals": ("cell structure and function explained", "cell the unit of life class 11 hindi"),
    "scientific_method": ("the scientific method explained for students", "scientific method hindi"),
    "reading_comprehension": ("how to improve reading comprehension", "reading comprehension tips hindi"),
    "english_communication": ("spoken english practice for beginners", "spoken english for beginners hindi"),
    "writing": ("how to write a good essay tips", "essay writing tips hindi"),
    "public_speaking": ("public speaking tips for students", "public speaking tips hindi"),
    "leadership_teamwork": ("teamwork and collaboration skills ted", "teamwork skills hindi"),
    "planning_organisation": ("time management tips for students", "time management for students hindi"),
    "drawing_sketching": ("how to draw for beginners sketching basics", "drawing for beginners hindi"),
    "hands_on_building": ("diy electronics projects for beginners", "simple electronics project at home hindi"),
    "empathy_listening": ("active listening skills", "active listening skills hindi"),
    "current_affairs": ("how to read the newspaper for upsc", "newspaper kaise padhe upsc hindi"),
    "physical_fitness": ("home workout for beginners no equipment", "home workout for beginners hindi"),
    "programming_fundamentals": ("programming for beginners full course", "c language tutorial for beginners hindi"),
    "python": ("python full course for beginners", "python tutorial for beginners hindi"),
    "data_structures_algorithms": ("data structures and algorithms full course", "data structures and algorithms hindi"),
    "web_development": ("web development full course html css javascript", "web development full course hindi"),
    "databases_sql": ("sql full course for beginners", "sql tutorial hindi"),
    "computer_networks": ("computer networking full course", "computer networks hindi"),
    "linux_command_line": ("linux command line for beginners", "linux commands tutorial hindi"),
    "software_engineering": ("git and github for beginners", "git and github tutorial hindi"),
    "data_analysis": ("data analysis with python pandas full course", "data analysis with python hindi"),
    "machine_learning": ("machine learning full course for beginners", "machine learning tutorial hindi"),
    "cybersecurity_fundamentals": ("cybersecurity full course for beginners", "cyber security course hindi"),
    "ethical_hacking": ("ethical hacking full course for beginners", "ethical hacking course hindi"),
    "circuits_electronics": ("basic electronics for beginners", "basic electronics hindi"),
    "embedded_systems": ("arduino tutorial for beginners", "arduino tutorial hindi"),
    "sensors_actuators": ("arduino sensors tutorial for beginners", "arduino sensors tutorial hindi"),
    "control_systems": ("control systems lectures introduction brian douglas", "control system lecture 1 hindi"),
    "mechanics": ("engineering mechanics introduction lecture", "engineering mechanics hindi"),
    "engineering_drawing_cad": ("autocad tutorial for beginners", "autocad tutorial hindi"),
    "thermodynamics": ("thermodynamics basics explained", "thermodynamics class 11 hindi"),
    "structural_design": ("structural analysis basics civil engineering", "structural analysis lecture hindi"),
    "electrical_power": ("electrical machines basics explained", "electrical machines hindi"),
    "aerodynamics": ("how airplanes fly aerodynamics explained", "how aeroplane fly hindi"),
    "chemical_processes": ("introduction to chemical engineering", "chemical engineering basics hindi lecture"),
    "robot_motion": ("robotics kinematics lecture", "robotics course hindi lecture"),
    "anatomy_physiology": ("anatomy and physiology introduction", "human anatomy hindi"),
    "pharmacology": ("pharmacology introduction basics", "pharmacology basics hindi"),
    "patient_care": ("basic nursing skills patient care", "nursing care hindi"),
    "clinical_reasoning": ("clinical reasoning for medical students", "clinical examination hindi"),
    "lab_techniques": ("basic laboratory techniques biology lab", "biology practical class 11 hindi"),
    "animal_care": ("veterinary science introduction animal care", "veterinary science course hindi"),
    "research_methods": ("research methodology basics", "research methodology hindi"),
    "visual_design": ("graphic design basics for beginners", "graphic design for beginners hindi"),
    "user_research": ("ux design full course for beginners", "ui ux design full course hindi"),
    "spatial_visualisation": ("spatial reasoning practice mirror images and paper folding", "mirror image water image reasoning hindi"),
    "accounting": ("accounting basics for beginners", "accountancy class 11 chapter 1 hindi"),
    "taxation_audit": ("income tax basics explained", "income tax basics hindi"),
    "financial_analysis": ("financial statement analysis basics", "financial statement analysis hindi"),
    "economics_concepts": ("microeconomics basics introduction", "microeconomics class 12 hindi"),
    "legal_reasoning": ("legal reasoning clat preparation lecture", "legal reasoning clat hindi lecture"),
    "argument_research": ("how to debate and argue well", "how to debate in hindi"),
    "governance_polity": ("indian polity basics constitution", "indian polity basics hindi"),
    "reporting_storytelling": ("how to write a news story journalism basics", "news writing journalism hindi"),
    "teaching_explaining": ("how to explain things clearly", "teaching skills hindi"),
    "hospitality_service": ("hotel management hospitality basics lecture", "hotel management basics hindi lecture"),
}

# Channels whose videos are picked first: educators and universities, Indian and international.
TRUSTED = {
    "freecodecamp.org", "khan academy", "khan academy india", "cs50", "mit opencourseware", "crashcourse", "ted-ed",
    "3blue1brown", "statquest with josh starmer", "programming with mosh", "corey schafer", "kaggle",
    "neso academy", "the organic chemistry tutor", "professor dave explains", "amoeba sisters", "ninja nerd",
    "osmosis from elsevier", "bozeman science", "nptel", "nptel-noc iitm", "iit kharagpur july 2018", "nptel iit madras",
    "codewithharry", "apna college", "jenny's lectures cs it", "gate smashers", "abdul bari", "physics wallah - alakh pandey",
    "physics wallah", "physics wallah foundation", "vedantu jee", "unacademy jee", "telusko", "kunal kushwaha", "take u forward", "love babbar",
    "study iq education", "drishti ias", "unacademy upsc", "ca wallah by pw", "commerce wallah by pw", "amit thinks",
    "simplilearn", "edureka!", "great learning", "learn engineering", "the engineering mindset", "paul mcwhorter",
    "dronebot workshop", "greatscott!", "electroboom", "engineering funda", "ekeeda", "learn coding",
    "khan sir official", "shiksha house", "magnet brains", "vedantu 9&10", "dear sir", "the economics guy",
    "ted", "ted-ed", "marques brownlee", "google career certificates", "ibm technology", "microsoft developer",
    "programming with harry", "chai aur code", "hitesh choudhary", "thapa technical", "techno gamerz",
    "learnvern", "great learning hindi", "mysirg.com", "wscube tech", "intellipaat", "eduonix learning solutions",
    "the cs50 channel", "harvard university", "stanford", "yale courses", "nptel - iitm", "iit bombay july 2018",
}


# Teach in Hindi: never the English pick.
HINDI_CHANNELS = {"codewithharry", "apna college", "gate smashers", "physics wallah - alakh pandey", "physics wallah foundation",
                  "study iq education",
                  "drishti ias", "magnet brains", "khan sir official", "dear sir", "chai aur code", "thapa technical",
                  "wscube tech", "learn coding", "neet wallah हिन्दी माध्यम", "pw up board 11th & 12th", "amit thinks",
                  "freecodecamp hindi", "gate wallah - me, ce, xe, ch, pi & es", "shesh chauhan it trainer",
                  "engineers ki pathshala by umesh dhande", "sheryians ai school", "next toppers - 11th science",
                  "study lovers kapil gangwani", "dca with rahul sir", "pw clat", "competition wallah",
                  "gate academy by umesh dhande", "imran sir maths"}
# Checked by hand and turned down: a motivational short, an animal-cell lesson for "animal care", a
# series preview, career advice instead of a lesson, a statistics episode for "reporting".
REJECTED = {"6fbE52YDEjU", "5ugDJhmmkFM", "kjBOesZCoqc", "onyB_X3zk6o", "ZwqOoD17_LU"}
# Career-information, motivation or clickbait channels: not lessons.
BLOCKED = {"quick support", "mr. indian hacker", "hafu go", "readers books club", "dr. vivek bindra: motivational speaker",
           "deepansh", "cm abhyudaya yojana- bareilly civil services", "brain station advanced", "lavanya global career planner",
           "careervidz", "beng hielscher", "jess cliffe", "robonyx"}


def search(query: str) -> list[dict]:
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query) + "&hl=en&gl=IN"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-IN,en;q=0.9"})
    html = urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "replace")
    m = re.search(r"var ytInitialData = (\{.*?\});</script>", html)
    if not m:
        return []
    found: list[dict] = []

    def walk(node):
        if isinstance(node, dict):
            if "videoRenderer" in node:
                v = node["videoRenderer"]
                found.append({"id": v.get("videoId"),
                              "title": "".join(r.get("text", "") for r in v.get("title", {}).get("runs", [])),
                              "channel": "".join(r.get("text", "") for r in v.get("ownerText", {}).get("runs", [])),
                              "length": (v.get("lengthText") or {}).get("simpleText"),
                              "views": (v.get("viewCountText") or {}).get("simpleText") or ""})
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(json.loads(m.group(1)))
    return found


def _seconds(length: str | None) -> int:
    if not length:
        return 0
    total = 0
    for part in length.split(":"):
        total = total * 60 + int(part)
    return total


def _views(text: str) -> int:
    digits = re.sub(r"[^\d]", "", text.split(" ")[0])
    return int(digits) if digits else 0


def verified(video_id: str) -> dict | None:
    """YouTube's own word that the video exists: its title and channel."""
    url = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(f"https://www.youtube.com/watch?v={video_id}")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=20) as r:
            return json.loads(r.read().decode())
    except Exception:  # noqa: BLE001 — not found / private / removed
        return None


def pick(results: list[dict], hindi: bool) -> dict | None:
    usable = [r for r in results if r["id"] and _seconds(r["length"]) >= 240 and "#shorts" not in r["title"].lower()
              and _views(r["views"]) >= 20_000 and r["channel"].lower() not in BLOCKED and r["id"] not in REJECTED]
    if not hindi:  # an English pick mustn't be a Hindi lesson
        usable = [r for r in usable if r["channel"].lower() not in HINDI_CHANNELS
                  and not re.search(r"hindi|हिंदी|हिन्दी|[\u0900-\u097F]", r["title"], re.I)]
    if hindi:  # a Hindi pick should say so, or come from a Hindi-teaching channel
        usable = [r for r in usable if re.search(r"hindi|हिंदी|हिन्दी", r["title"], re.I)
                  or r["channel"].lower() in HINDI_CHANNELS] or usable
    trusted = [r for r in usable if r["channel"].lower() in TRUSTED]
    return (trusted or [r for r in usable if _views(r["views"]) >= 200_000] or [None])[0]


def main(only: list[str]) -> None:
    out = json.loads(OUT.read_text()) if OUT.exists() else {"skills": {}}
    today = date.today().isoformat()
    for skill, (en, hi) in QUERIES.items():
        if only and skill not in only:
            continue
        entry = {"query": {"en": en, "hi": hi}, "videos": []}
        for lang, query in (("en", en), ("hi", hi)):
            try:
                chosen = pick(search(query), hindi=lang == "hi")
            except Exception as e:  # noqa: BLE001 — a failed search keeps the search link only
                print(f"  {skill} {lang}: search failed: {e}", file=sys.stderr)
                chosen = None
            time.sleep(1.5)
            if chosen is None or any(v["id"] == chosen["id"] for v in entry["videos"]):
                continue  # nothing good — or the English pick again: the search link covers it
            check = verified(chosen["id"])
            if not check or check.get("title") != chosen["title"]:
                print(f"  {skill} {lang}: {chosen['id']} didn't verify", file=sys.stderr)
                continue
            entry["videos"].append({"lang": lang, "id": chosen["id"], "title": check["title"],
                                    "channel": check.get("author_name", chosen["channel"]), "length": chosen["length"],
                                    "checked": today})
            time.sleep(0.5)
        out["skills"][f"skill:{skill}"] = entry
        print(f"{skill}: " + " | ".join(f"[{v['lang']}] {v['title'][:60]} — {v['channel']}" for v in entry["videos"]))
    out["about"] = ("Topic videos for each skill, found by scripts/find_videos.py and checked against YouTube's oEmbed "
                    "on the date given. Shown with a QR code to open on a phone.")
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")


if __name__ == "__main__":
    main(sys.argv[1:])
