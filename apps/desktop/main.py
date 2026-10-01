import sys

from PySide6.QtWidgets import QApplication

from app import touch_calibration
from app.fonts import load_fonts
from app.main_window import MainWindow
from app.theme import STYLESHEET


def main() -> None:
    app = QApplication(sys.argv)
    load_fonts()
    app.setStyleSheet(STYLESHEET)

    # X forgets a touch calibration when it exits (and a desktop's rc.xml can lose it); put it
    # back before anything is tapped.
    problem = touch_calibration.apply_saved()
    if problem and problem != "no saved calibration":
        print(f"Touch calibration not applied: {problem}", file=sys.stderr)

    window = MainWindow()
    if "--kiosk" in sys.argv:
        window.enter_kiosk_mode()
    else:
        window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
