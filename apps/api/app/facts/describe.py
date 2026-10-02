"""Facts in words: attribute names in English and Hindi, and values as a student reads them —
"₹1,25,000 a year", "Bhopal Junction, 6.2 km (straight line)", "Yes". Shared by the OKF bundle's
readable bodies, MAYA's tools and the screens."""

from __future__ import annotations

NAMES = {
    "fee.tuition.annual": ("Tuition fee", "ट्यूशन फ़ीस"),
    "fee.hostel.annual": ("Hostel fee", "हॉस्टल फ़ीस"),
    "fee.mess.annual": ("Mess fee", "मेस फ़ीस"),
    "fee.one_time": ("One-time fees", "एक बार की फ़ीस"),
    "fee.total.first_year": ("First-year total", "पहले साल का कुल"),
    "fee.waiver": ("Fee waivers", "फ़ीस में छूट"),
    "facility.hostel": ("Hostel", "हॉस्टल"),
    "facility.medical": ("Medical facility", "चिकित्सा सुविधा"),
    "facility.library": ("Library", "लाइब्रेरी"),
    "facility.labs": ("Labs", "लैब"),
    "facility.sports": ("Sports", "खेल"),
    "facility.internet": ("Internet", "इंटरनेट"),
    "location.website": ("Official website", "आधिकारिक वेबसाइट"),
    "location.address": ("Address", "पता"),
    "location.coordinates": ("Map location", "नक्शे पर जगह"),
    "near.railway_station": ("Nearest railway station", "नज़दीकी रेलवे स्टेशन"),
    "near.airport": ("Nearest airport", "नज़दीकी हवाई अड्डा"),
    "near.hospital": ("Nearest hospital", "नज़दीकी अस्पताल"),
    "near.bus_stand": ("Nearest bus stand", "नज़दीकी बस अड्डा"),
    "near.pharmacy": ("Nearest pharmacy", "नज़दीकी दवा की दुकान"),
    "near.atm": ("Nearest ATM", "नज़दीकी एटीएम"),
    "admission.page": ("Admissions page", "प्रवेश पेज"),
    "admission.exam": ("Entrance exam", "प्रवेश परीक्षा"),
    "admission.route": ("Admission route", "प्रवेश का रास्ता"),
    "admission.application_window": ("Applications", "आवेदन"),
    "admission.exam_date": ("Exam date", "परीक्षा की तारीख़"),
    "admission.counselling": ("Counselling", "काउंसलिंग"),
    "admission.result_date": ("Result", "परिणाम"),
    "academic.university": ("University", "विश्वविद्यालय"),
    "academic.established": ("Established", "स्थापना"),
    "ranking.nirf.engineering": ("NIRF rank (engineering)", "NIRF रैंक (इंजीनियरिंग)"),
    "ranking.nirf.medical": ("NIRF rank (medical)", "NIRF रैंक (मेडिकल)"),
    "placement.median_salary": ("Median salary", "औसत (मीडियन) वेतन"),
    "placement.students_placed": ("Students placed", "प्लेसमेंट पाए छात्र"),
}
PER = {"year": ("a year", "सालाना"), "semester": ("a semester", "प्रति सेमेस्टर"), "month": ("a month", "प्रति माह"),
       "once": ("once", "एक बार"), "course": ("for the whole course", "पूरे कोर्स के लिए")}


def name(attribute: str, lang: str = "en") -> str:
    if attribute not in NAMES and attribute.count(".") > 1 and ".".join(attribute.split(".")[:2]) in NAMES:
        attribute = ".".join(attribute.split(".")[:2])  # admission.exam_date.session_1 → its kind
    en, hi = NAMES.get(attribute, (attribute.split(".")[-1].replace("_", " ").capitalize(),) * 2)
    return hi if lang == "hi" else en


def inr(amount: float | int) -> str:
    """Indian digit grouping: 125000 → ₹1,25,000."""
    whole = int(round(amount))
    sign, digits = ("-" if whole < 0 else ""), str(abs(whole))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        digits = ",".join(([head] if head else []) + groups + [tail])
    return f"{sign}₹{digits}"


def value_text(attribute: str, value, lang: str = "en") -> str:
    if value is None:  # looked, not found — not "doesn't exist"
        return "आधिकारिक स्रोतों में नहीं मिला" if lang == "hi" else "Not found in official sources"
    if isinstance(value, bool):
        return ("हाँ" if value else "नहीं") if lang == "hi" else ("Yes" if value else "No")
    if isinstance(value, dict):
        if "amount" in value:
            per = PER.get(value.get("per", ""), ("", ""))[1 if lang == "hi" else 0]
            text = f"{inr(value['amount'])} {per}".strip()
            if value.get("applies_to") and value["applies_to"] not in ("all", "general"):
                text += f" ({value['applies_to']})"
            return text
        if "name" in value and "km" in value:
            how = "सीधी दूरी" if lang == "hi" else "straight line"
            return f"{value['name']}, {value['km']:g} km ({how})"
        if "lat" in value and "lng" in value:
            return f"{value['lat']:.4f}, {value['lng']:.4f}"
        if "from" in value:
            from datetime import date

            def day(iso: str) -> str:
                try:
                    return date.fromisoformat(iso).strftime("%-d %b %Y")
                except (TypeError, ValueError):
                    return str(iso)

            span = f"{day(value['from'])} – {day(value['to'])}" if value.get("to") and value["to"] != value["from"] else day(value["from"])
            return f"{value['label']}: {span}" if value.get("label") else span
        if "route" in value:
            via = "से" if lang == "hi" else "via"
            n = value.get("programmes")
            count = (f" ({n} प्रोग्राम)" if lang == "hi" else f" ({n} programme{'s' if n != 1 else ''})") if n else ""
            return f"{value['route']} {via} {value.get('exam', '')}{count}".strip()
        if "rank" in value:
            return f"{value['rank']} ({value.get('category', '')} {value.get('year', '')})".replace("( ", "(").strip()
        if "text" in value:
            return str(value["text"])
    return str(value)
