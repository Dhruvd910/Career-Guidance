import pytest

from app.voice_parsing import (
    clean_dictation, extract_name, is_meaningful, parse_class, parse_exam_choice, parse_number, parse_yes_no,
)


@pytest.mark.parametrize("transcript, expected", [
    ("Dhruv", "Dhruv"),
    ("Dhruv.", "Dhruv"),
    ("My name is Dhruv.", "Dhruv"),
    ("Hello, my name is Dhruv.", "Dhruv"),
    ("Hi MAYA, I'm Priya Sharma.", "Priya Sharma"),
    ("Yes, my name is Arjun", "Arjun"),
    ("Myself Rahul.", "Rahul"),
    ("My good name is Ananya.", "Ananya"),
    ("Dhruv this side", "Dhruv"),
    ("I am Mohammed Aamir Khan", "Mohammed Aamir Khan"),
    ("My name is Dhruv and I'm in class 11.", "Dhruv"),
    ("you can call me Sam", "Sam"),
    ("priya", "Priya"),
    ("My name is Maya.", "Maya"),  # a student named Maya must not be filtered out
])
def test_extract_name(transcript, expected):
    assert extract_name(transcript) == expected


@pytest.mark.parametrize("transcript", ["", " .", "Thank you.", "My name is", "Hello."])
def test_extract_name_rejects_non_answers(transcript):
    assert extract_name(transcript) is None


@pytest.mark.parametrize("transcript, expected", [
    ("11", 11), ("Class 12.", 12), ("I'm in 11th.", 11), ("tenth", 10),
    ("I study in class eleven", 11), ("Twelfth standard.", 12), ("8th", 8), ("nine", 9),
    ("plus two", 12), ("Plus one.", 11), ("first year PUC", 11), ("second PUC", 12),
    ("Inter second year", 12),
])
def test_parse_class(transcript, expected):
    assert parse_class(transcript) == expected


@pytest.mark.parametrize("transcript", ["", "I'm sixteen years old", "Thank you.", "class 7"])
def test_parse_class_rejects_out_of_range_or_empty(transcript):
    assert parse_class(transcript) is None


@pytest.mark.parametrize("transcript, expected", [
    ("Yes", True), ("Yeah, I know.", True), ("Haan", True), ("Of course!", True),
    ("No", False), ("Not sure yet.", False), ("I don't know", False), ("Nahi", False),
    ("I'm confused.", False),
])
def test_parse_yes_no(transcript, expected):
    assert parse_yes_no(transcript) is expected


def test_parse_yes_no_negation_beats_yes_word():
    assert parse_yes_no("I'm not sure") is False  # contains "sure"


@pytest.mark.parametrize("transcript, expected", [
    ("JEE", "jee"), ("Engineering.", "jee"), ("I want to go to IIT", "jee"),
    ("NEET", "neet"), ("Neat.", "neet"), ("I want to be a doctor", "neet"), ("MBBS", "neet"),
    ("Something else", "careers"), ("Law", "careers"),
])
def test_parse_exam_choice(transcript, expected):
    assert parse_exam_choice(transcript) == expected


@pytest.mark.parametrize("transcript, expected", [
    ("45,000", 45000), ("My rank is 45000.", 45000), ("1.5 lakh", 150000),
    ("45 thousand", 45000), ("98.6", 98.6), ("12k", 12000),
])
def test_parse_number(transcript, expected):
    assert parse_number(transcript) == expected


def test_parse_number_none_without_digits():
    assert parse_number("I don't know my rank") is None


@pytest.mark.parametrize("transcript, meaningful", [
    ("Dhruv", True), ("", False), (" .", False), ("Thank you.", False), ("you", False),
])
def test_is_meaningful(transcript, meaningful):
    assert is_meaningful(transcript) is meaningful


def test_clean_dictation_strips_trailing_period_only():
    assert clean_dictation("Maharashtra.") == "Maharashtra"
    assert clean_dictation("St. Xavier's") == "St. Xavier's"


# ---------------- setup wizard answers ----------------

from app.voice_parsing import (  # noqa: E402
    matching_states, parse_board, parse_category, parse_state, wants_to_go_back, wants_to_skip,
)


@pytest.mark.parametrize("said, board", [
    ("CBSE", "CBSE"), ("C.B.S.E.", "CBSE"), ("I study in CBSC.", "CBSE"), ("c b s e board", "CBSE"),
    ("Central board", "CBSE"), ("ICSE.", "ICSE"), ("I.C.S.E", "ICSE"), ("ISC", "ICSE"),
    ("State board.", "State Board"), ("Maharashtra board", "State Board"), ("SSC", "State Board"),
    ("Kerala syllabus", "State Board"), ("IB", "Other"), ("IGCSE", "Other"), ("Something else", "Other"),
    ("Thank you.", None), ("I don't know", None),
])
def test_parse_board(said, board):
    assert parse_board(said) == board


@pytest.mark.parametrize("said, state", [
    ("Maharashtra.", "Maharashtra"), ("I live in Tamil Nadu", "Tamil Nadu"), ("tamilnadu", "Tamil Nadu"),
    ("UP", "Uttar Pradesh"), ("I'm from U.P.", "Uttar Pradesh"), ("I live in Pune.", "Maharashtra"),
    ("Bangalore", "Karnataka"), ("New Delhi", "Delhi"), ("Orissa", "Odisha"), ("West Bengal", "West Bengal"),
    ("Andhra Pradesh", "Andhra Pradesh"), ("Madhya Pradesh", "Madhya Pradesh"), ("Jammu and Kashmir", "Jammu and Kashmir"),
    ("J&K", "Jammu and Kashmir"), ("Chattisgarh", "Chhattisgarh"), ("Pondicherry", "Puducherry"),
    ("Hold it up please", None), ("Thank you.", None), ("Pradesh", None),
])
def test_parse_state(said, state):
    assert parse_state(said) == state


def test_matching_states():
    assert matching_states("ma")[:3] == ["Madhya Pradesh", "Maharashtra", "Manipur"]
    assert matching_states("kar")[0] == "Karnataka"
    assert matching_states("pune") == ["Maharashtra"]
    assert matching_states("k") == []


@pytest.mark.parametrize("said, category", [
    ("General", "General"), ("General category.", "General"), ("Open", "General"), ("OBC", "OBC"),
    ("O.B.C.", "OBC"), ("OBC NCL", "OBC"), ("S.C.", "SC"), ("SC", "SC"), ("ST", "ST"),
    ("Scheduled tribe", "ST"), ("Scheduled caste", "SC"), ("EWS", "EWS"), ("E W S", "EWS"),
    ("Thank you.", None), ("I'm not sure", None),
])
def test_parse_category(said, category):
    assert parse_category(said) == category


def test_go_back_and_skip():
    assert wants_to_go_back("Go back.") and wants_to_go_back("back") and wants_to_go_back("Previous please")
    assert not wants_to_go_back("I want to come back to Delhi")
    assert wants_to_skip("Skip.") and wants_to_skip("I'd prefer not to say") and wants_to_skip("I don't want to tell")
    assert not wants_to_skip("General")


def test_is_unsure():
    from app.voice_parsing import is_unsure
    assert is_unsure("I don't know") and is_unsure("No idea") and is_unsure("I'm not sure")
    assert not is_unsure("No") and not is_unsure("Maharashtra") and not is_unsure("")


# ---------------- multiple choice ----------------

from app.voice_parsing import match_option  # noqa: E402

FEELINGS = [
    {"id": "love", "label": "I love it", "keywords": ["love", "favourite", "really enjoy"]},
    {"id": "like", "label": "I like it", "keywords": ["like", "okay", "fine", "enjoy"]},
    {"id": "meh", "label": "Not really my thing", "keywords": ["not really", "don't like", "boring"]},
    {"id": "hard", "label": "I struggle with it", "keywords": ["struggle", "hate", "difficult"]},
]


@pytest.mark.parametrize("said, option", [
    ("I love it!", "love"), ("It's my favourite subject.", "love"), ("I like it.", "like"),
    ("It's okay.", "like"), ("I don't like it much.", "meh"), ("Not really.", "meh"),
    ("Honestly it's boring.", "meh"), ("I struggle with it.", "hard"), ("It's difficult for me", "hard"),
    ("The second one", "like"), ("Option C", "meh"), ("Number 4", "hard"), ("B", "like"),
    ("The last one", "hard"), ("Thank you.", None), ("Purple elephants", None),
])
def test_match_option(said, option):
    assert match_option(said, FEELINGS) == option
