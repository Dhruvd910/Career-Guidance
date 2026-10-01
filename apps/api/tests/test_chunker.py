"""Cutting a streamed reply into speakable sentences."""

import pytest

from app.conversation.chunker import SentenceSplitter, speakable


def split(*pieces, max_chars=220):
    splitter = SentenceSplitter(max_chars)
    out = []
    for piece in pieces:
        out += splitter.feed(piece)
    return out + splitter.flush()


def stream_char_by_char(text, **kw):
    return split(*text, **kw)


def test_sentences_come_out_as_soon_as_they_are_complete():
    splitter = SentenceSplitter()
    assert splitter.feed("Engineering is one path. ") == ["Engineering is one path."]
    assert splitter.feed("Medicine is") == []
    assert splitter.feed(" another! What do you enjoy? ") == ["Medicine is another!", "What do you enjoy?"]
    assert splitter.flush() == []


def test_the_last_sentence_waits_for_the_end_of_the_stream():
    splitter = SentenceSplitter()
    assert splitter.feed("Is that a yes?") == [], "nothing follows the '?' yet"
    assert splitter.flush() == ["Is that a yes?"]


@pytest.mark.parametrize("text, expected", [
    ("Fees are ₹1.5 lakh a year. Hostel is extra.", ["Fees are ₹1.5 lakh a year.", "Hostel is extra."]),
    ("The fee is ₹1,20,000. That includes tuition.", ["The fee is ₹1,20,000.", "That includes tuition."]),
    ("A B.Tech takes four years. An M.Tech two more.", ["A B.Tech takes four years.", "An M.Tech two more."]),
    ("Do a B.Sc. in physics first. Then decide.", ["Do a B.Sc. in physics first.", "Then decide."]),
    ("Talk to Dr. Rao about it. He knows.", ["Talk to Dr. Rao about it.", "He knows."]),
    ("Like A. P. J. Abdul Kalam did. Inspiring.", ["Like A. P. J. Abdul Kalam did.", "Inspiring."]),
    ("Check nta.ac.in for dates. Then register.", ["Check nta.ac.in for dates.", "Then register."]),
    ("Really?! Yes. Wait...  Okay.", ["Really?!", "Yes.", "Wait...", "Okay."]),
    ('She said "go for it." So I did.', ['She said "go for it."', "So I did."]),
])
def test_full_stops_that_do_not_end_a_sentence(text, expected):
    assert split(text) == expected
    assert stream_char_by_char(text) == expected, "however the stream happens to be cut"


def test_hindi_sentences_end_at_the_danda():
    text = "कोई बात नहीं। चलो देखते हैं कि दिक्कत कहाँ है। तुम्हें कौन सा subject पसंद है?"
    assert stream_char_by_char(text) == [
        "कोई बात नहीं।", "चलो देखते हैं कि दिक्कत कहाँ है।", "तुम्हें कौन सा subject पसंद है?",
    ]


def test_hinglish_in_english_letters():
    assert split("Koi baat nahi, yeh normal hai. Tumhe kya pasand hai?") == [
        "Koi baat nahi, yeh normal hai.", "Tumhe kya pasand hai?",
    ]


def test_a_very_long_sentence_is_cut_at_a_comma():
    long = ("If you enjoy maths and building things, engineering could suit you, and if you like biology "
            "and helping people, medicine is worth a look, while design, law and commerce are good paths "
            "too, depending on what excites you most about the future you want")
    pieces = stream_char_by_char(long + ".", max_chars=120)
    assert len(pieces) >= 2 and all(len(p) <= 121 for p in pieces)
    assert " ".join(pieces) == long + "."


def test_markdown_and_list_markers_are_not_read_aloud():
    text = "**Medicine** is one option.\n1. MBBS takes five years.\n- Nursing is shorter.\n\n## Next"
    assert split(text) == ["Medicine is one option.", "MBBS takes five years.", "Nursing is shorter.", "Next"]


def test_punctuation_alone_is_not_a_sentence():
    assert split("Okay. ... !") == ["Okay."]


def test_speakable_collapses_whitespace():
    assert speakable("  `JEE`   Main\n\nis  hard ") == "JEE Main is hard"
