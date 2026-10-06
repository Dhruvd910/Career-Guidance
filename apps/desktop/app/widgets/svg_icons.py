"""The design's icons, as small inline SVGs rendered to pixmaps.

Outline icons use `currentColor`, which is swapped for the colour asked for. The five
dashboard glyphs are drawn solid in their own colours, the way the design has them.
"""

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_OUTLINE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
)

OUTLINE = {
    "arrow-right": '<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>',
    "arrow-left": '<path d="M19 12H5"/><path d="m11 18-6-6 6-6"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    "x": '<path d="M6 6l12 12"/><path d="M18 6 6 18"/>',
    "mic": '<rect x="9" y="3" width="6" height="11" rx="3" fill="currentColor"/>'
           '<path d="M5.5 11a6.5 6.5 0 0 0 13 0"/><path d="M12 17.5V21"/>',
    "send": '<path d="M21 3 10.5 13.5"/><path d="m21 3-6.5 18-4-7.5L3 9.5z" fill="currentColor"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 '
                '2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 '
                '0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 '
                '1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 '
                '0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 '
                '0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 '
                '9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    # the review table
    "user": '<circle cx="12" cy="8" r="4" fill="currentColor"/><path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7z" fill="currentColor"/>',
    "class": '<path d="M12 4 2 9l10 5 10-5z" fill="currentColor"/><path d="M6 11.5V16c3.5 3 8.5 3 12 0v-4.5" '
             'fill="currentColor"/><path d="M21 9.5V15"/>',
    "board": '<path d="M3 5.5c3-1.5 6-1.5 9 .5v14c-3-2-6-2-9-.5z" fill="currentColor"/>'
             '<path d="M21 5.5c-3-1.5-6-1.5-9 .5v14c3-2 6-2 9-.5z" fill="currentColor"/>',
    "pin": '<path d="M12 22s7-6.2 7-12a7 7 0 0 0-14 0c0 5.8 7 12 7 12z" fill="currentColor"/>'
           '<circle cx="12" cy="10" r="2.6" fill="#ffffff" stroke="none"/>',
    "home": '<path d="M3 11 12 3l9 8v10h-6v-6H9v6H3z" fill="currentColor"/>',
    "help": '<circle cx="12" cy="12" r="9.5"/><path d="M9.5 9.2a2.6 2.6 0 0 1 5 .8c0 1.8-2.5 2.2-2.5 4"/>'
            '<circle cx="12" cy="17.3" r=".9" fill="currentColor"/>',
    "play": '<path d="M8 5.5v13l10.5-6.5z" fill="currentColor"/>',
    "users": '<circle cx="9" cy="8" r="3.5" fill="currentColor"/><path d="M2 20c0-3.9 3.1-6 7-6s7 2.1 7 6z" '
             'fill="currentColor"/><circle cx="17" cy="9" r="2.8" fill="currentColor"/>'
             '<path d="M17.5 13.5c2.6.3 4.5 2.2 4.5 5.5h-4" fill="currentColor"/>',
}

# The dashboard glyphs: solid, in the tile's colour, with white detail.
SOLID = {
    "mic-badge": '<circle cx="24" cy="24" r="23" fill="#e8f0fe"/><rect x="19" y="10" width="10" height="18" rx="5" '
                 'fill="{c}"/><path d="M14 23a10 10 0 0 0 20 0M24 33v5" fill="none" stroke="{c}" stroke-width="3" '
                 'stroke-linecap="round"/>',
    "compass": '<circle cx="24" cy="24" r="22" fill="{c}"/><circle cx="24" cy="24" r="15" fill="none" '
               'stroke="#fff" stroke-width="2.5"/><path d="M31 17 26.5 26.5 17 31l4.5-9.5z" fill="#fff"/>'
               '<circle cx="24" cy="24" r="2" fill="{c}"/>',
    "cap": '<path d="M24 8 2 19l22 11 22-11z" fill="{c}"/><path d="M11 25v9c7 6 19 6 26 0v-9l-13 6.5z" '
           'fill="{c}"/><path d="M43 20v11" stroke="{c}" stroke-width="3" stroke-linecap="round"/>'
           '<circle cx="43" cy="33" r="3" fill="{c}"/>',
    "exam": '<path d="M12 3h17l10 10v29a3 3 0 0 1-3 3H12a3 3 0 0 1-3-3V6a3 3 0 0 1 3-3z" fill="{c}"/>'
            '<path d="M29 3v10h10" fill="#fff" fill-opacity=".45"/><path d="M16 22h16M16 29h16M16 36h10" '
            'stroke="#fff" stroke-width="3" stroke-linecap="round"/>',
    "clipboard": '<rect x="8" y="7" width="32" height="38" rx="5" fill="{c}"/><rect x="16" y="3" width="16" '
                 'height="9" rx="3" fill="{c}" stroke="#fff" stroke-width="2"/><path d="m16 27 6 6 11-12" '
                 'fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>',
    "bulb": '<path d="M24 3a15 15 0 0 0-9 27v5h18v-5A15 15 0 0 0 24 3z" fill="{c}"/>'
            '<rect x="16" y="37" width="16" height="4" rx="2" fill="{c}"/><rect x="19" y="43" width="10" height="3.5" '
            'rx="1.75" fill="{c}"/><path d="m17.5 18 5 5 8-9" fill="none" stroke="#fff" stroke-width="3.5" '
            'stroke-linecap="round" stroke-linejoin="round"/>',
    "video": '<rect x="2" y="8" width="44" height="32" rx="8" fill="{c}"/><path d="M19.5 16v16l13-8z" fill="#fff"/>',
    "chart": '<rect x="5" y="27" width="9" height="16" rx="2.5" fill="{c}"/><rect x="19.5" y="17" width="9" height="26" '
             'rx="2.5" fill="{c}"/><rect x="34" y="6" width="9" height="37" rx="2.5" fill="{c}"/>',
    "road": '<path d="M17 4h14l13 40H4z" fill="{c}"/><path d="M24 8v6M24 20v7M24 33v8" stroke="#fff" '
            'stroke-width="3.5" stroke-linecap="round"/>',
}


def _render(svg: str, size: int, width: int | None = None) -> QPixmap:
    ratio = QGuiApplication.instance().devicePixelRatio() if QGuiApplication.instance() else 1.0
    w = width or size
    pixmap = QPixmap(int(w * ratio), int(size * ratio))
    pixmap.fill(Qt.transparent)
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(0, 0, w * ratio, size * ratio))
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


_cache: dict[tuple, QPixmap] = {}


def icon_pixmap(name: str, color: str = "#0f1f3d", size: int = 20, stroke: float = 2.0) -> QPixmap:
    key = (name, color, size, stroke)
    if key not in _cache:
        if name in SOLID:
            svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">{SOLID[name].format(c=color)}</svg>'
        else:
            svg = _OUTLINE.format(w=stroke, body=OUTLINE[name]).replace("currentColor", color)
        _cache[key] = _render(svg, size)
    return _cache[key]


def svg_icon(name: str, color: str = "#0f1f3d", size: int = 20, stroke: float = 2.0) -> QIcon:
    return QIcon(icon_pixmap(name, color, size, stroke))
