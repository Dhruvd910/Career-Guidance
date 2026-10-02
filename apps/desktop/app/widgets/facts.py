"""Facts on screen (spec §24: "Do not hide the source"). Every value shows where it came from and
how fresh it is — "NIT Trichy (official website) · Verified 3 days ago" — in a colour that says
whether it's fresh, stale or unchecked. Tap a value for the document it came from: its words,
page, dates, and a QR code to open it on a phone. A conflict shows both values.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QSizePolicy, QVBoxLayout

from app.widgets.common import Card, heading, muted, primary_button

STATE_COLOURS = {"fresh": "#15803d", "stale": "#b45309", "unverified": "#64748b", "not_available": "#64748b"}
KINDS = {"government": ("Government", "सरकारी"), "institution": ("The college's own", "कॉलेज का अपना"),
         "admission_portal": ("Official admission portal", "आधिकारिक प्रवेश पोर्टल"), "regulator": ("Regulator", "नियामक"),
         "dataset": ("Open dataset", "खुला डेटासेट"), "secondary": ("Not an official source", "आधिकारिक स्रोत नहीं")}
OSM = ("Places © OpenStreetMap contributors (ODbL). Distances are straight-line; roads are longer.",
       "जगहें © OpenStreetMap योगदानकर्ता (ODbL)। दूरियाँ सीधी रेखा में हैं; सड़क से ज़्यादा होंगी।")


def _words(view: dict, key: str, lang: str) -> str:
    value = view.get(key) or {}
    return value.get(lang) or value.get("en") or ""


def chip_text(view: dict, lang: str) -> str:
    source = view["source"]
    kind = "" if source.get("official") else (" · " + KINDS.get(source.get("kind"), KINDS["secondary"])[1 if lang == "hi" else 0])
    year = f" · {view['academic_year']}" if view.get("academic_year") else ""
    return f"{source['name']}{kind}{year} · {view['label'][lang] if lang in view['label'] else view['label']['en']}"


class FactRow(QPushButton):
    """One value with its source and freshness; tapping it opens the source."""

    def __init__(self, view: dict, lang: str, parent=None):
        super().__init__()
        self.view = view
        self.setProperty("variant", "option")
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)
        top = QLabel(f"<b>{_words(view, 'what', lang)}:</b> {_words(view, 'text', lang)}")
        top.setWordWrap(True)
        top.setStyleSheet("background: transparent;")
        layout.addWidget(top)
        chip = QLabel(chip_text(view, lang))
        chip.setWordWrap(True)
        colour = "#b91c1c" if view["status"] == "conflicted" else STATE_COLOURS.get(view["label"].get("state"), "#64748b")
        chip.setStyleSheet(f"background: transparent; color: {colour}; font-size: 12px;")
        layout.addWidget(chip)
        for other in view.get("conflict") or []:
            also = QLabel(("दूसरा स्रोत कहता है: " if lang == "hi" else "Another source says: ")
                          + f"{_words(other, 'text', lang)} ({other['source']['name']})")
            also.setWordWrap(True)
            also.setStyleSheet("background: transparent; color: #b91c1c; font-size: 12px;")
            layout.addWidget(also)
        if view.get("conflict"):
            note = QLabel("इन्हें मिलाया नहीं जा सका — कॉलेज से पक्का करें।" if lang == "hi"
                          else "These couldn't be reconciled — please confirm with the college.")
            note.setWordWrap(True)
            note.setStyleSheet("background: transparent; color: #b91c1c; font-size: 12px;")
            layout.addWidget(note)
        self.setMinimumHeight(layout.sizeHint().height() + 4)
        self.clicked.connect(lambda: SourceDialog(view, lang, parent or self).exec())


class SourceDialog(QDialog):
    def __init__(self, view: dict, lang: str, parent=None):
        super().__init__(parent)
        self.setModal(True)
        src = view["source"]
        hi = lang == "hi"
        self.setWindowTitle(src["document"])
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.addWidget(heading(f"{_words(view, 'what', lang)}: {_words(view, 'text', lang)}"))
        lines = [
            (("स्रोत: " if hi else "Source: ") + src["name"] + f" ({KINDS.get(src['kind'], ('', ''))[1 if hi else 0]})"),
            ("दस्तावेज़: " if hi else "Document: ") + src["document"] + (f", {src['locator']}" if src.get("locator") else ""),
        ]
        if view.get("academic_year"):
            lines.append(("शैक्षणिक वर्ष: " if hi else "Academic year: ") + view["academic_year"])
        lines.append(("लिया गया: " if hi else "Retrieved: ") + (view.get("retrieved_at") or "")[:10]
                     + " · " + (view["label"].get(lang) or view["label"]["en"]))
        if view.get("verified_by") == "human":
            lines.append("एक व्यक्ति ने जाँचा" if hi else "Checked by a person")
        elif view.get("verified_by") == "auto" and view["status"] not in ("unverified", "not_available"):
            lines.append("दस्तावेज़ से अपने-आप पढ़ा गया" if hi else "Read automatically from the document")
        for text in lines:
            layout.addWidget(muted(text))
        if view.get("quote"):
            quote = QLabel(f"“{view['quote']}”")
            quote.setWordWrap(True)
            quote.setStyleSheet("font-style: italic; color: #334155;")
            layout.addWidget(quote)
        try:
            from app.qr import qr_pixmap

            code = QLabel()
            code.setPixmap(qr_pixmap(src["url"], 160))
            code.setAlignment(Qt.AlignCenter)
            layout.addWidget(code)
        except Exception:  # noqa: BLE001 — the address alone still works
            pass
        link = QLabel(src["url"])
        link.setWordWrap(True)
        link.setStyleSheet("font-size: 12px; color: #4f46e5;")
        layout.addWidget(link)
        close = primary_button("ठीक है" if hi else "Done")
        close.clicked.connect(self.accept)
        layout.addWidget(close)


def facts_card(title: str, views: dict[str, dict], lang: str, parent, empty: str, skip: tuple[str, ...] = (),
               note: str | None = None) -> Card:
    card = Card()
    card.addWidget(heading(title))
    shown = [v for a, v in views.items() if a not in skip]
    if not shown:
        card.addWidget(muted(empty))
    for view in shown:
        card.addWidget(FactRow(view, lang, parent))
    if note and shown:
        card.addWidget(muted(note))
    return card


def osm_note(lang: str) -> str:
    return OSM[1 if lang == "hi" else 0]


def cell_text(cell: dict | None, lang: str = "en") -> tuple[str, str]:
    """A comparison cell: its value, and its source and freshness, or 'not known'."""
    if not cell:
        return ("पता नहीं" if lang == "hi" else "Not known", "")
    label = cell["label"].get(lang) or cell["label"]["en"]
    conflict = (" · " + ("स्रोतों में मतभेद" if lang == "hi" else "sources disagree")) if cell.get("conflict") else ""
    return cell["value"], f"{cell['source']} · {label}{conflict}"
