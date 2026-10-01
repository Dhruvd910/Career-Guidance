from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = APP_DIR / "assets"
MAYA_ASSETS_DIR = ASSETS_DIR / "maya"
# 480px-wide copies written by scale_mascots.sh: decoding the 1600x960 originals every frame
# costs more than a CPU core on the Pi. Optional — the originals are used when they're absent.
SCALED_MASCOTS_DIR = MAYA_ASSETS_DIR / "scaled"
# The same animations cropped tight around MAYA (222x320): the originals are 3/4 empty
# space, so a full-height MAYA beside a question card needs these.
PORTRAIT_MASCOTS_DIR = MAYA_ASSETS_DIR / "portrait"
PORTRAIT_RATIO = 222 / 320
FONTS_DIR = ASSETS_DIR / "fonts"


def mascot_gif(name: str, portrait: bool = False):
    if portrait and (PORTRAIT_MASCOTS_DIR / f"{name}.gif").is_file():
        return PORTRAIT_MASCOTS_DIR / f"{name}.gif"
    scaled = SCALED_MASCOTS_DIR / f"{name}.gif"
    return scaled if scaled.is_file() else MAYA_ASSETS_DIR / f"{name}.gif"

VOSK_MODEL_DIR = APP_DIR / "models" / "vosk-model-small-en-in-0.4"

API_BASE_URL = "http://127.0.0.1:8000"

APP_ORG = "AICareerGuide"
APP_NAME = "MAYA"

CATEGORIES = ["General", "EWS", "OBC", "SC", "ST"]
EXAM_STATUSES = [
    ("planning", "Planning to prepare"),
    ("preparing", "Currently preparing"),
    ("appeared", "Appeared, awaiting result"),
    ("qualified", "Have my result / rank"),
]
SUBJECTS_BY_EXAM = {
    "JEE_MAIN": ["Physics", "Chemistry", "Maths"],
    "JEE_ADVANCED": ["Physics", "Chemistry", "Maths"],
    "NEET_UG": ["Physics", "Chemistry", "Biology"],
}
