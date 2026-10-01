"""Layout choices that depend on the screen the app is running on.

The kiosk panel is 800x480 and the sidebar takes 220 of that, leaving pages about 566px
wide — narrower than a phone. Multi-column grids and wide margins that look right on a
monitor push content off the side there, so pages ask these helpers instead of hardcoding.
"""

from PySide6.QtWidgets import QApplication

COMPACT_WIDTH = 1000
COMPACT_HEIGHT = 700


def is_compact() -> bool:
    screen = QApplication.primaryScreen().availableGeometry()
    return screen.width() < COMPACT_WIDTH or screen.height() < COMPACT_HEIGHT


def page_margins() -> tuple[int, int, int, int]:
    return (14, 12, 14, 12) if is_compact() else (28, 28, 28, 28)


def columns(wide: int, compact: int = 1) -> int:
    """How many cards fit side by side."""
    return compact if is_compact() else wide
