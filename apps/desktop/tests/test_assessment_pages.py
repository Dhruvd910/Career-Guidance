"""The assessment screens: the hub, taking one by touch and by voice (three languages), results,
how you've changed, and the career directions."""

import pytest
from PySide6.QtWidgets import QLabel, QPushButton

from app.pages import assessment_result, assessment_runner, assessments, directions
from app.pages.assessment_result import AssessmentHistoryPage, AssessmentResultPage
from app.pages.assessment_runner import AssessmentRunnerPage
from app.pages.assessments import AssessmentsPage
from app.pages.directions import DirectionPage, DirectionsPage

T = lambda en, hi: {"en": en, "hi": hi}  # noqa: E731

MATHS = {"key": "int_maths", "type": "choice", "section": T("Subjects", "विषय"),
         "prompt": T("How do you feel about maths?", "मैथ्स आपको कैसा लगता है?"),
         "options": [{"key": "love", "label": T("I love it", "बहुत पसंद है"),
                      "keywords": {"en": ["love"], "hi": ["बहुत पसंद"], "hinglish": ["bahut pasand"]}},
                     {"key": "like", "label": T("I like it", "पसंद है"), "keywords": {"en": ["like"], "hi": [], "hinglish": []}},
                     {"key": "meh", "label": T("Not really my thing", "ज़्यादा नहीं"), "keywords": {}},
                     {"key": "hard", "label": T("I struggle with it", "मुश्किल लगता है"), "keywords": {}}],
         "say": "Let's find out. How do you feel about maths?", "answer": None}
PROBLEM = {"key": "a_num_1", "type": "problem", "section": T("Numbers", "संख्याएँ"),
           "prompt": T("A pen costs ₹12. How much do 5 pens cost?", "एक पेन ₹12 का है। 5 पेन कितने के होंगे?"),
           "options": [{"key": k, "label": T(v, v), "keywords": {}} for k, v in zip("abcd", ["₹50", "₹60", "₹62", "₹72"])],
           "say": "A pen costs ₹12…", "answer": None}
MARKS = {"key": "jr_maths", "type": "marks", "section": T("Marks", "अंक"),
         "prompt": T("Maths: what percentage did you get?", "मैथ्स: कितने प्रतिशत?"), "options": [], "say": "Maths?",
         "answer": None}
RESULT = {"attempt_id": 5, "instrument": "aptitude", "version": 1, "title": T("Thinking skills", "सोचने की क्षमता"),
          "method": "correct_answers", "form": "A", "language": "en", "completed_at": "2026-10-03T10:00:00+00:00",
          "scores": [{"dimension": "aptitude:numerical", "group": "aptitude", "label": T("working with numbers", "संख्याएँ"),
                      "score": 0.8, "n_items": 5, "detail": {}, "says": T("4 of 5 right, 1 skipped", "5 में से 4 सही")}],
          "review": [{"key": "a_num_1", "prompt": PROBLEM["prompt"], "code": None,
                      "options": [{"key": o["key"], "label": o["label"]} for o in PROBLEM["options"]],
                      "picked": "a", "answer": "b", "right": False, "explanation": T("12 × 5 = 60.", "12 × 5 = 60।")}]}


def view(item, answered=0, estimate=10, language="en", can_go_back=None):
    return {"attempt_id": 9, "status": "in_progress", "language": language, "complete": False,
            "instrument": {"key": "x", "version": 1, "title": T("X", "X")}, "item": item,
            "progress": {"answered": answered, "estimate": estimate},
            "can_go_back": answered > 0 if can_go_back is None else can_go_back}


class FakeApi:
    def __init__(self):
        self.calls = []
        self.next_view = view(PROBLEM, answered=1)
        self.interpretation = {"answer": None, "skip": False}
        self.first = view(MATHS)

    def assessment_start(self, key, language="en", mode="touch"):
        self.calls.append(("start", key, language))
        return {**self.first, "language": language}

    def assessment_answer(self, attempt_id, item_key, answer=None, skipped=False, transcript=None,
                          interpreted_by="touch", response_ms=None):
        self.calls.append(("answer", item_key, answer, skipped, transcript, interpreted_by))
        return self.next_view

    def assessment_back(self, attempt_id):
        self.calls.append(("back",))
        return view({**MATHS, "answer": {"option": "like"}})

    def assessment_interpret(self, attempt_id, item_key, transcript):
        self.calls.append(("interpret", item_key, transcript))
        return self.interpretation

    def assessment_instruments(self):
        def one(key, title, done=None, unfinished=None, times=0):
            return {"key": key, "version": 1, "category": "x", "title": title, "about": T("about", "बारे में"),
                    "est_minutes": 6, "times_taken": times, "last_completed": done, "in_progress": unfinished}
        return [one("interests", T("What you enjoy", "आपको क्या पसंद है"),
                    done={"attempt_id": 1, "completed_at": "2026-10-01T10:00:00+00:00"}, times=2),
                one("aptitude", T("Thinking skills", "सोचने की क्षमता"), unfinished={"attempt_id": 2, "answered": 6}),
                one("skills", T("Your skills", "आपके हुनर"))]

    def assessment_result(self, attempt_id):
        return RESULT

    def assessment_history(self, key):
        row = lambda dim, label, before, after, change: {  # noqa: E731
            "dimension": dim, "label": T(label, label), "before": T(before, before), "after": T(after, after),
            "before_score": 0.4, "after_score": 0.8, "change": change, "note": None}
        rows = [row("aptitude:numerical", "working with numbers", "2 of 5 right", "4 of 5 right", 1),
                row("aptitude:logical", "logical reasoning", "4 of 5 right", "4 of 5 right", 0)]
        attempt = {**RESULT}
        return {"instrument": key, "attempts": [attempt, attempt], "since_first": rows, "since_previous": rows}

    def delete_assessment_attempt(self, attempt_id):
        self.calls.append(("delete", attempt_id))

    def career_directions(self):
        return DIRECTIONS

    def career_direction(self, key):
        return CSE


CSE = {"career_key": "cse", "name": "Computer Science & Software Engineering", "domain": "Engineering & Technology",
       "band": "strong", "band_label": T("Strong alignment", "मज़बूत मेल"),
       "components": {"interest": 0.9, "work_style": 0.6, "aptitude:logical": None},
       "measures": [{"dimension": "aptitude:logical", "label": T("logical reasoning", "तार्किक सोच"), "weight": 3,
                     "score": None, "says": None},
                    {"dimension": "academic:maths", "label": T("Maths marks", "मैथ्स के अंक"), "weight": 3,
                     "score": 0.78, "says": T("78%", "78%")}],
       "why": [T("You enjoy maths", "आपको मैथ्स पसंद है")], "strengths": [T("Maths marks: 78%", "मैथ्स के अंक: 78%")],
       "development_areas": [], "questions": [T("Could you sit with one stubborn bug?", "क्या आप…?")],
       "not_measured": [], "things_to_try": ["Try CS50"], "education_path": "PCM → B.Tech", "exams": ["JEE_MAIN"],
       "evidence": []}
LAW = {**CSE, "career_key": "law", "name": "Law", "domain": "Law", "band": "weak",
       "band_label": T("Less likely from your answers", "कम मेल"), "why": []}
DIRECTIONS = {"ready": True, "missing": ["aptitude"], "inputs": {"interests": 1},
              "as_of": "2026-10-03T10:00:00+00:00", "summary": {"strong": ["cse"], "weak": ["law"]},
              "domains": [{"domain": "Engineering & Technology", "label": T("Engineering & Technology", "इंजीनियरिंग"),
                           "best_band": "strong", "careers": [CSE]},
                          {"domain": "Law", "label": T("Law", "क़ानून"), "best_band": "weak", "careers": [LAW]}]}


class FakeVoice:
    def __init__(self):
        from PySide6.QtCore import QObject, Signal

        class Signals(QObject):
            state_changed = Signal(str)

        self._signals = Signals()
        self.state_changed = self._signals.state_changed
        self.asked, self.said, self.cancelled = [], [], 0

    def ask(self, text, on_answer, on_no_answer=None, language=None):
        self.asked.append((text, language, on_answer, on_no_answer))

    def say(self, text, on_done=None, language=None):
        self.said.append((text, language))

    def cancel(self):
        self.cancelled += 1


class Window:
    def __init__(self):
        self.voice = FakeVoice()
        self.went = []
        self.pages = {}
        self.assessment_language = None

    def navigate(self, name, **kwargs):
        self.went.append((name, kwargs))

    def refresh_back_button(self):
        pass


@pytest.fixture()
def api(monkeypatch):
    fake = FakeApi()
    now = lambda fn, *a, on_success=None, on_error=None: on_success and on_success(fn(*a))  # noqa: E731
    for module in (assessments, assessment_runner, assessment_result, directions):
        monkeypatch.setattr(module, "api_client", fake)
        monkeypatch.setattr(module, "run_async", now)
    return fake


def texts(widget):
    return [w.text() for w in widget.findChildren(QLabel) + widget.findChildren(QPushButton) if w.isVisibleTo(widget)]


def button(widget, text):
    """The visible button showing `text` — replaced ones linger, hidden, until Qt deletes them."""
    return next(b for b in widget.findChildren(QPushButton) if b.isVisibleTo(widget)
                and (b.text() == text or any(lbl.text() == text for lbl in b.findChildren(QLabel))))


# ---------------- the hub ----------------

def test_the_hub_shows_each_check_and_its_state(qapp, api):
    page = AssessmentsPage(Window())
    page.on_show()
    shown = texts(page)
    assert "What you enjoy  ·  about 6 min" in shown and "Last taken 1 Oct · 2 times" in shown
    assert "Unfinished — 6 answered. It picks up where you stopped." in shown and "Continue" in shown
    assert "Not taken yet" in shown and "How I've changed" in shown
    assert page.directions_btn.isEnabled()
    page.set_language("hi")
    assert "आपको क्या पसंद है  ·  लगभग 6 मिनट" in texts(page)
    button(page, "Start").click()
    assert page.ctx.went[-1] == ("assessment_run", {"key": "skills", "language": "hi"})


# ---------------- taking one ----------------

@pytest.fixture()
def runner(qapp, api):
    page = AssessmentRunnerPage(Window())
    page.isVisible = lambda: True
    page.on_show(key="interests", language="en")
    return page


def test_a_question_is_shown_read_out_and_answered_by_a_tap(runner, api):
    assert runner.prompt.text() == "How do you feel about maths?"
    assert runner.ctx.voice.asked[-1][:2] == ("Let's find out. How do you feel about maths?", "en")
    assert not runner.back_btn.isEnabled()
    button(runner, "I like it").click()
    assert api.calls[-1][:6] == ("answer", "int_maths", {"option": "like"}, False, None, "touch")
    assert runner.prompt.text() == PROBLEM["prompt"]["en"] and "A    ₹50" in texts(runner)


def test_a_spoken_answer_in_hinglish_is_matched_on_the_pi(runner, api):
    _, _, on_answer, _ = runner.ctx.voice.asked[-1]
    on_answer("mujhe maths bahut pasand hai")
    assert api.calls[-1] == ("answer", "int_maths", {"option": "love"}, False, "mujhe maths bahut pasand hai", "keywords")
    assert not [c for c in api.calls if c[0] == "interpret"]


def test_an_unusual_answer_goes_to_the_interpreter(runner, api):
    api.interpretation = {"answer": {"option": "love"}, "skip": False}
    _, _, on_answer, _ = runner.ctx.voice.asked[-1]
    on_answer("maths toh meri jaan hai")
    assert ("interpret", "int_maths", "maths toh meri jaan hai") in api.calls
    assert api.calls[-1][2] == {"option": "love"} and api.calls[-1][5] == "llm"


def test_not_understood_twice_leaves_it_to_a_tap(runner, api):
    _, _, on_answer, _ = runner.ctx.voice.asked[-1]
    on_answer("the weather is nice")
    again, _, on_answer, _ = runner.ctx.voice.asked[-1]
    assert again.startswith("Sorry, I didn't catch that.")
    on_answer("still the weather")
    assert "tap an answer" in runner.hint.text() and len(runner.ctx.voice.asked) == 2
    assert not [c for c in api.calls if c[0] == "answer"]


def test_going_back_and_skipping_by_voice(runner, api):
    _, _, on_answer, _ = runner.ctx.voice.asked[-1]
    on_answer("chhodo")
    assert api.calls[-1][:4] == ("answer", "int_maths", None, True)
    api.next_view = view(MATHS, answered=1)
    _, _, on_answer, _ = runner.ctx.voice.asked[-1]
    on_answer("peeche")
    assert api.calls[-1] == ("back",)
    assert button(runner, "I like it").property("selected") == "true", "the earlier answer is shown"


def test_a_late_voice_answer_for_an_old_question_is_ignored(runner, api):
    _, _, old_answer, _ = runner.ctx.voice.asked[-1]
    button(runner, "I love it").click()
    count = len(api.calls)
    old_answer("I struggle with it")
    assert len(api.calls) == count


def test_marks_on_a_number_pad(runner, api):
    api.next_view = view(MARKS, answered=1)
    button(runner, "I love it").click()
    for key in ("1", "0", "1"):
        button(runner, key).click()
    assert not runner.marks_next.isEnabled(), "101% isn't a mark"
    button(runner, "⌫").click()
    button(runner, "⌫").click()
    button(runner, "7").click()
    assert runner.marks_display.text() == "17 %" and runner.marks_next.isEnabled()
    runner.marks_next.click()
    assert api.calls[-1][2] == {"value": 17.0}


def test_in_hindi_the_english_is_shown_small_except_for_problems(qapp, api):
    page = AssessmentRunnerPage(Window())
    page.isVisible = lambda: True
    api.first = view(MATHS, language="hi")
    page.on_show(key="interests", language="hi")
    assert page.prompt.text() == "मैथ्स आपको कैसा लगता है?" and page.prompt_en.text() == "How do you feel about maths?"
    assert page.ctx.voice.asked[-1][1] == "hi"
    api.next_view = view(PROBLEM, answered=1, language="hi")
    button(page, "बहुत पसंद है").click()
    assert page.prompt.text() == PROBLEM["prompt"]["hi"] and not page.prompt_en.isVisibleTo(page)


def test_finishing_opens_the_result(runner, api):
    api.next_view = {"attempt_id": 9, "status": "completed", "complete": True, "result": RESULT,
                     "instrument": {"key": "aptitude"}, "language": "en"}
    button(runner, "I love it").click()
    assert runner.ctx.went[-1] == ("assessment_result", {"result": RESULT, "fresh": True})


# ---------------- results ----------------

def test_a_result_with_its_answers_to_go_through_and_delete(qapp, api):
    page = AssessmentResultPage(Window())
    page.on_show(attempt_id=5)
    shown = texts(page)
    assert "Thinking skills" in shown and "4 of 5 right, 1 skipped" in shown and "Taken 3 Oct" in shown
    button(page, "Go through the answers").click()
    assert "You: ₹50   ·   Right answer: ₹60" in texts(page)
    page.delete_btn.click()
    assert ("delete", 5) not in api.calls and page.delete_btn.text() == "Tap again to delete it for good"
    page.delete_btn.click()
    assert ("delete", 5) in api.calls and page.ctx.went[-1] == ("assessment", {})


def test_how_ive_changed_only_beyond_the_noise(qapp, api):
    page = AssessmentHistoryPage(Window())
    page.on_show(key="aptitude")
    shown = texts(page)
    assert "Working with numbers:  2 of 5 right  →  4 of 5 right" in shown and "Improved" in shown
    assert "About the same" in shown


# ---------------- career directions ----------------

def test_directions_in_bands_with_the_less_likely_one_tap_away(qapp, api):
    page = DirectionsPage(Window())
    page.on_show()
    shown = texts(page)
    assert "Engineering & Technology" in shown and "Strong alignment" in shown and "You enjoy maths" in shown
    assert "Law" not in " ".join(shown).replace("Show 1 less likely from your answers", "")
    assert not any("best" in t.lower() for t in shown)
    button(page, "Show 1 less likely from your answers").click()
    assert "Less likely from your answers" in texts(page)
    button(page, "Thinking skills").click()
    assert page.ctx.went[-1] == ("assessment_run", {"key": "aptitude", "language": "en"})


def test_one_direction_explained_and_talked_over_with_maya(qapp, api):
    page = DirectionPage(Window())
    page.on_show(key="cse")
    shown = texts(page)
    assert "Why it may fit" in shown and "•  You enjoy maths" in shown
    assert "Logical reasoning — not measured yet" in shown and "78%" in shown
    assert "•  Could you sit with one stubborn bug?" in shown and "•  PCM → B.Tech" in shown
    page.talk.click()
    name, kwargs = page.ctx.went[-1]
    assert name == "maya" and "Computer Science & Software Engineering" in kwargs["ask"]
    page.set_language("hi")
    assert "यह क्यों जँच सकता है" in texts(page) and "मज़बूत मेल" in texts(page)


def test_no_directions_before_what_you_enjoy(qapp, api, monkeypatch):
    monkeypatch.setattr(api, "career_directions", lambda: {"ready": False, "missing": ["interests"], "domains": []})
    page = DirectionsPage(Window())
    page.on_show()
    assert "Start with “What you enjoy”" in texts(page)
