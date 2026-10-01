"""The touch calibration maths: raw panel values -> screen position."""

import pytest

from calibrate_touch import CalibrationError, apply_matrix, conf_snippet, solve_affine

CORNERS = [(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)]


def fit(raw_of):
    """Solve from four corner touches, where raw_of(sx, sy) is what the panel reports."""
    return solve_affine([(*raw_of(sx, sy), sx, sy) for sx, sy in CORNERS])


def assert_maps(matrix, raw, expected, tolerance=1e-6):
    x, y = apply_matrix(matrix, *raw)
    assert x == pytest.approx(expected[0], abs=tolerance)
    assert y == pytest.approx(expected[1], abs=tolerance)


def test_a_panel_that_is_already_right_solves_to_no_change():
    matrix = fit(lambda sx, sy: (sx, sy))
    assert_maps(matrix, (0.5, 0.5), (0.5, 0.5))


def test_an_upside_down_panel_is_corrected():
    matrix = fit(lambda sx, sy: (1 - sx, 1 - sy))
    assert_maps(matrix, (1 - 0.3, 1 - 0.7), (0.3, 0.7))


def test_swapped_axes_are_corrected():
    matrix = fit(lambda sx, sy: (sy, sx))
    assert_maps(matrix, (0.8, 0.25), (0.25, 0.8))


def test_a_panel_using_part_of_its_range_is_stretched_back():
    # Typical resistive behaviour: the corners of the screen sit well inside the ADC range.
    matrix = fit(lambda sx, sy: (0.2 + sx * 0.6, 0.15 + sy * 0.7))
    assert_maps(matrix, (0.2 + 0.5 * 0.6, 0.15 + 0.5 * 0.7), (0.5, 0.5))


def test_a_small_touch_error_stays_a_small_mapping_error():
    # Nobody hits a crosshair exactly; the fit must not amplify that.
    wobble = {0: (0.004, -0.003), 1: (-0.002, 0.004), 2: (0.003, 0.002), 3: (-0.004, -0.002)}
    samples = [
        (sx + wobble[i][0], sy + wobble[i][1], sx, sy) for i, (sx, sy) in enumerate(CORNERS)
    ]
    matrix = solve_affine(samples)
    x, y = apply_matrix(matrix, 0.5, 0.5)
    # 0.02 of an 800x480 panel is ~16px — within a fingertip.
    assert abs(x - 0.5) < 0.02 and abs(y - 0.5) < 0.02


def test_touches_too_close_together_are_rejected():
    with pytest.raises(CalibrationError):
        solve_affine([(0.5, 0.5, sx, sy) for sx, sy in CORNERS])


def test_the_snippet_names_the_device_and_matrix():
    snippet = conf_snippet("ADS7846 Touchscreen", "1 0 0 0 1 0 0 0 1")
    assert 'MatchProduct "ADS7846 Touchscreen"' in snippet
    assert 'Option       "CalibrationMatrix" "1 0 0 0 1 0 0 0 1"' in snippet
