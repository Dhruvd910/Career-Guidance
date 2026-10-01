"""Calibrating the touchscreen on the Raspberry Pi desktop (labwc): rc.xml and the reload."""

import re
import signal

import pytest

from app import labwc_input, touch_calibration

DEVICE = "ADS7846 Touchscreen"
MATRIX = [1.058324, 0.010929, -0.038537, -0.029482, 1.106627, -0.061508, 0.0, 0.0, 1.0]

# Exactly what Raspberry Pi OS's autotouch script writes at first login.
PI_OS_RC = (
    '<?xml version="1.0"?>\n'
    '<openbox_config xmlns="http://openbox.org/3.4/rc">\n'
    f'\t<touch deviceName="{DEVICE}" mapToOutput="HDMI-A-1" mouseEmulation="yes"/>\n'
    "</openbox_config>\n"
)


@pytest.fixture()
def hups(monkeypatch):
    """Records the SIGHUPs that would have reached labwc."""
    sent = []
    monkeypatch.setenv("LABWC_PID", "4242")
    monkeypatch.setattr(labwc_input.os, "kill", lambda pid, sig: sent.append((pid, sig)))
    return sent


def test_calibration_goes_into_pi_os_rc_and_labwc_reloads(labwc_rc, hups):
    labwc_rc.parent.mkdir(parents=True)
    labwc_rc.write_text(PI_OS_RC)

    assert labwc_input.set_calibration(MATRIX, DEVICE) is None

    text = labwc_rc.read_text()
    assert "ns0" not in text and 'xmlns="http://openbox.org/3.4/rc"' in text
    assert f'<device category="{DEVICE}">' in text
    assert "<calibrationMatrix>1.058324 0.010929 -0.038537 -0.029482 1.106627 -0.061508</calibrationMatrix>" in text
    assert hups == [(4242, signal.SIGHUP)]


def test_pi_os_touch_line_survives_so_autotouch_leaves_the_file_alone(labwc_rc, hups):
    labwc_rc.parent.mkdir(parents=True)
    labwc_rc.write_text(PI_OS_RC)
    labwc_input.set_calibration(MATRIX, DEVICE)
    # autotouch's own check (grep "touch.*mouseEmulation"): a match means "already set up".
    assert any(re.search("touch.*mouseEmulation", line) for line in labwc_rc.read_text().splitlines())
    assert 'mapToOutput="HDMI-A-1"' in labwc_rc.read_text()


def test_the_same_matrix_again_changes_nothing(labwc_rc, hups):
    labwc_input.set_calibration(MATRIX, DEVICE)
    before = labwc_rc.read_text()
    assert labwc_input.set_calibration(MATRIX, DEVICE) is None
    assert labwc_rc.read_text() == before
    assert len(hups) == 1, "MAYA re-applies at every start; that mustn't reload labwc every time"


def test_a_new_calibration_replaces_the_old_one(labwc_rc, hups):
    labwc_input.set_calibration(MATRIX, DEVICE)
    newer = [1.0, 0.0, 0.01, 0.0, 1.0, 0.02, 0.0, 0.0, 1.0]
    labwc_input.set_calibration(newer, DEVICE)
    text = labwc_rc.read_text()
    assert text.count("<calibrationMatrix>") == 1 and text.count("<device ") == 1
    assert labwc_input.current_calibration(DEVICE) == pytest.approx(newer[:6])


def test_no_rc_xml_yet_starts_one(labwc_rc, hups):
    assert labwc_input.set_calibration(MATRIX, DEVICE) is None
    assert labwc_rc.read_text().startswith("<?xml")
    assert "<labwc_config>" in labwc_rc.read_text()
    assert labwc_input.current_calibration(DEVICE) == pytest.approx(MATRIX[:6])


def test_other_settings_and_comments_are_kept(labwc_rc, hups):
    labwc_rc.parent.mkdir(parents=True)
    labwc_rc.write_text(
        "<labwc_config>\n  <!-- my keybinds -->\n  <keyboard><keybind key=\"W-t\"/></keyboard>\n"
        "  <libinput><device category=\"touchpad\"><tap>yes</tap></device></libinput>\n</labwc_config>\n")
    labwc_input.set_calibration(MATRIX, DEVICE)
    text = labwc_rc.read_text()
    assert "<!-- my keybinds -->" in text and 'key="W-t"' in text
    assert '<device category="touchpad">' in text and "<tap>yes</tap>" in text
    assert text.count("<libinput>") == 1, "added to the existing libinput block"


def test_a_broken_rc_xml_is_left_alone(labwc_rc, hups):
    labwc_rc.parent.mkdir(parents=True)
    labwc_rc.write_text("<labwc_config><oops></labwc_config>")
    problem = labwc_input.set_calibration(MATRIX, DEVICE)
    assert problem and "valid XML" in problem
    assert labwc_rc.read_text() == "<labwc_config><oops></labwc_config>"
    assert not hups


def test_a_matrix_must_have_nine_values(hups):
    assert "9 values" in labwc_input.set_calibration([1, 0, 0])


def test_on_labwc_applying_goes_to_rc_xml_not_x(labwc_rc, hups):
    assert touch_calibration.apply(MATRIX, DEVICE) is None
    assert labwc_input.current_calibration(DEVICE) == pytest.approx(MATRIX[:6])


@pytest.fixture()
def panel(monkeypatch, tmp_path):
    """A readable touchscreen, and no calibration of MAYA's own saved yet."""
    monkeypatch.setattr(touch_calibration, "CALIBRATION_FILE", tmp_path / "touch_calibration.json")
    monkeypatch.setattr(touch_calibration, "find_touch_device", lambda: ("/dev/input/event7", DEVICE))
    monkeypatch.setattr(touch_calibration.os, "access", lambda path, mode: True)


def test_on_labwc_an_uncalibrated_panel_asks_for_calibration(panel, hups):
    assert touch_calibration.needs_calibration() is True


def test_on_labwc_a_panel_calibrated_in_rc_xml_does_not_ask(panel, hups):
    labwc_input.set_calibration(MATRIX, DEVICE)
    assert touch_calibration.needs_calibration() is False
