"""MAYA's own touch calibration: the crosshair flow, keeping the result, and the X plumbing."""

import os

import pytest

from app import touch_calibration, x11_input
from app.widgets.calibration_view import CalibrationView, describe_result


@pytest.fixture()
def calibration_file(tmp_path, monkeypatch):
    path = tmp_path / "touch_calibration.json"
    monkeypatch.setattr(touch_calibration, "CALIBRATION_FILE", path)
    return path


@pytest.fixture()
def view(qapp):
    # /dev/null stands in for the panel; touches are fed in directly.
    v = CalibrationView(os.devnull)
    v.resize(800, 480)
    yield v
    v.shutdown()


def raw_for(fx, fy):
    """What an upside-down panel whose useful range is 10%-90% of the ADC would report."""
    rx = 0.1 + (1 - fx) * 0.8
    ry = 0.1 + (1 - fy) * 0.8
    return int(rx * touch_calibration.RAW_MAX), int(ry * touch_calibration.RAW_MAX)


def test_four_taps_and_a_check_produce_a_matrix(view):
    results = []
    view.finished.connect(lambda matrix, error: results.append((matrix, error)))
    view.start()
    for _label, fx, fy in touch_calibration.TARGETS:
        view._on_touch(*raw_for(fx, fy))
    assert not results, "four taps solve it; the fifth checks it"
    view._on_touch(*raw_for(0.5, 0.5))

    assert len(results) == 1
    matrix, error = results[0]
    assert len(matrix) == 9 and matrix[6:] == [0.0, 0.0, 1.0]
    assert error < 2, "a perfect check tap lands on the target"
    # The solved matrix undoes the panel's flip: a raw corner maps back to that screen corner.
    x, y = touch_calibration.apply_matrix(tuple(matrix), *(v / touch_calibration.RAW_MAX for v in raw_for(0.1, 0.9)))
    assert x == pytest.approx(0.1, abs=0.002) and y == pytest.approx(0.9, abs=0.002)


def test_a_sloppy_check_tap_is_reported(view):
    results = []
    view.finished.connect(lambda matrix, error: results.append(error))
    view.start()
    for _label, fx, fy in touch_calibration.TARGETS:
        view._on_touch(*raw_for(fx, fy))
    view._on_touch(*raw_for(0.56, 0.5))  # 6% of 800px wide = ~48px off
    accurate, message = describe_result(results[0])
    assert 40 < results[0] < 56
    assert not accurate and "again" in message


def test_the_same_spot_four_times_asks_to_try_again(view):
    failures = []
    view.failed.connect(failures.append)
    view.start()
    for _ in touch_calibration.TARGETS:
        view._on_touch(2000, 2000)
    assert failures and "too close" in failures[0]


def test_touches_are_ignored_when_not_calibrating(view):
    results = []
    view.finished.connect(lambda *a: results.append(a))
    for _ in range(6):
        view._on_touch(100, 100)
    assert view.step == 0 and not results


def test_a_saved_calibration_round_trips(calibration_file):
    matrix = [1.1, 0.0, -0.05, 0.0, 1.2, -0.1, 0.0, 0.0, 1.0]
    touch_calibration.save("ADS7846 Touchscreen", matrix, 7.5)
    loaded = touch_calibration.load()
    assert loaded["matrix"] == matrix and loaded["device"] == "ADS7846 Touchscreen"


def test_skipping_means_not_asking_again(calibration_file, monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")
    touch_calibration.mark_skipped()
    assert touch_calibration.load() is None, "a skip isn't a calibration"
    assert touch_calibration.needs_calibration() is False, "…but it stops the first-start prompt"


def test_no_x_display_means_no_prompt(calibration_file, monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    assert touch_calibration.needs_calibration() is False


def test_without_x_applying_explains_instead_of_crashing(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    problem = x11_input.set_calibration([1, 0, 0, 0, 1, 0, 0, 0, 1])
    assert problem and "DISPLAY" in problem


def test_a_matrix_must_have_nine_values():
    assert "9 values" in x11_input.set_calibration([1, 0, 0])


def test_floats_are_packed_the_way_xinput_packs_them():
    for value in (1.0, -0.125, 0.3333, 0.0):
        assert x11_input.item_to_float(x11_input.float_to_item(value)) == pytest.approx(value, abs=1e-6)
    assert x11_input.float_to_item(1.0) == 0x3F800000
