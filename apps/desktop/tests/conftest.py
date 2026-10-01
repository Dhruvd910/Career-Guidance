import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(autouse=True)
def no_echo_canceller(monkeypatch):
    """Tests don't depend on whether this machine happens to run MAYA's echo canceller; those
    that need it say so."""
    from app import audio_io

    monkeypatch.setattr(audio_io, "echo_cancelled", lambda: False)


@pytest.fixture(autouse=True)
def labwc_rc(tmp_path, monkeypatch):
    """Tests never see the real desktop: run from a desktop terminal, LABWC_PID would otherwise
    send calibrations into the user's own ~/.config/labwc/rc.xml (and SIGHUP labwc)."""
    from app import labwc_input

    monkeypatch.delenv("LABWC_PID", raising=False)
    path = tmp_path / "labwc" / "rc.xml"
    monkeypatch.setattr(labwc_input, "rc_path", lambda: path)
    return path


_PAGES = []


@pytest.fixture(autouse=True)
def pages_live_like_in_the_app(monkeypatch):
    """In MAYA the main window's stack owns every page for the whole run. A test page that only
    Python holds can be freed while widgets it cleared are still waiting on deleteLater (their
    buttons' slots are what keep it alive): Qt then deletes those widgets twice, and the process
    dies in whichever later test first runs an event loop. So test pages are kept too."""
    from app.pages.base import BasePage

    init = BasePage.__init__

    def keep(self, *args, **kwargs):
        init(self, *args, **kwargs)
        _PAGES.append(self)

    monkeypatch.setattr(BasePage, "__init__", keep)


@pytest.fixture(scope="session")
def qapp():
    # One QApplication for the whole run. A test file that created a plain QCoreApplication
    # first would make every later QWidget abort the process.
    return QApplication.instance() or QApplication([])
