"""Turning an expected percentile or score into an estimated rank — for students who don't
have a rank yet but want to see where they'd stand.

These are estimates from the most recent official cycle, and every result says so:

- JEE Main: NTA's own approximation, rank ≈ (100 − percentile) × candidates / 100, using the
  2026 figure of 15,38,468 unique candidates who appeared across both sessions (NTA result
  statistics, April 2026).
- NEET-UG: interpolated from the Re-NEET 2026 marks-vs-rank data (NTA scorecards compiled by
  Careers360). The published table has a few out-of-order rows (individual scorecards); only
  a monotone set of points is kept. Marks-to-rank shifts a lot between years — 600 marks was
  about AIR 1,400 in 2025 but about AIR 10,500 in the easier 2026 re-exam — so this is the
  least certain estimate in the app.
"""

from __future__ import annotations

from bisect import bisect_left

JEE_MAIN_CANDIDATES = 1_538_468
JEE_MAIN_BASIS = ("JEE Main 2026: 15,38,468 unique candidates appeared (NTA). "
                  "Rank ≈ (100 − percentile) × candidates ÷ 100.")

# (marks, AIR) — Re-NEET 2026, monotone subset of the published table.
NEET_2026 = [
    (715, 1), (710, 4), (705, 8), (700, 19), (696, 46), (681, 253), (660, 883), (653, 1_277),
    (641, 2_100), (631, 3_318), (622, 4_667), (615, 6_151), (608, 7_700), (600, 10_469),
    (590, 13_700), (579, 18_600), (575, 20_000), (566, 25_600), (560, 29_500), (554, 34_000),
    (549, 37_500), (542, 44_000), (535, 50_000), (525, 59_000), (510, 77_000), (500, 90_000),
    (493, 100_000), (474, 127_000), (460, 150_000), (444, 178_000), (433, 200_000), (410, 250_000),
    (400, 270_000), (389, 300_000), (372, 347_000), (355, 400_000), (340, 450_000), (325, 500_000),
    (312, 550_000), (299, 600_000), (275, 700_000), (253, 800_000), (232, 900_000), (212, 1_000_000),
    (193, 1_100_000), (176, 1_200_000), (159, 1_300_000), (143, 1_400_000), (126, 1_500_000),
    (110, 1_600_000), (102, 1_650_000),
]
NEET_BASIS = ("Re-NEET 2026 marks vs rank (NTA scorecards via Careers360). Marks-to-rank changes a "
              "lot from year to year, so treat this as a rough guide.")
NEET_MAX = 720


class EstimateError(ValueError):
    pass


def jee_main_rank_from_percentile(percentile: float) -> int:
    if not 0 <= percentile <= 100:
        raise EstimateError("A percentile is between 0 and 100.")
    return max(1, round((100 - percentile) * JEE_MAIN_CANDIDATES / 100))


def neet_rank_from_score(score: float) -> int:
    if not 0 <= score <= NEET_MAX:
        raise EstimateError("A NEET score is between 0 and 720.")
    points = sorted(NEET_2026)  # ascending by marks
    marks = [m for m, _r in points]
    if score >= marks[-1]:
        return 1
    if score <= marks[0]:
        return points[0][1]  # below the table: the tail of the list
    i = bisect_left(marks, score)
    (m0, r0), (m1, r1) = points[i - 1], points[i]
    if m1 == m0:
        return r1
    return max(1, round(r0 + (score - m0) * (r1 - r0) / (m1 - m0)))


def estimate_rank(exam_code: str, percentile: float | None = None, score: float | None = None) -> tuple[int, str]:
    """(estimated rank, where the estimate comes from)."""
    if exam_code == "JEE_MAIN" and percentile is not None:
        return jee_main_rank_from_percentile(percentile), JEE_MAIN_BASIS
    if exam_code == "NEET_UG" and score is not None:
        return neet_rank_from_score(score), NEET_BASIS
    raise EstimateError("Enter your rank" + (
        ", or your expected percentile to estimate it." if exam_code == "JEE_MAIN" else
        ", or your expected score to estimate it." if exam_code == "NEET_UG" else "."
    ))
