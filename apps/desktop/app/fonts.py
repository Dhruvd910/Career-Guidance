"""Loads the design's bundled fonts (Poppins for everything, Caveat for the handwritten
touches). Must run after QApplication exists and before any widget is styled."""

from PySide6.QtGui import QFontDatabase

from app.config import FONTS_DIR


def load_fonts() -> None:
    for path in sorted(FONTS_DIR.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(path))
