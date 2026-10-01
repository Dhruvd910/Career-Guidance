"""MAYA answers in the language the student uses: English, Hindi or Hinglish."""

import asyncio

import pytest

from app.ai import orchestrator
from app.ai.language import (
    DEVANAGARI, ENGLISH, HINDI, HINGLISH, LATIN, LanguageTag, detect, language_from_whisper, language_of_text,
    reply_instruction, updated_stats, usual_language, voice_for,
)
from app.providers.stt import GroqWhisperSTT
from tests.fakes import FakeLLM, FakeSTT
from app.routers import ai as ai_router


@pytest.mark.parametrize("text, expected", [
    ("Which colleges can I get with rank 5000?", ENGLISH),
    ("मुझे कौन सा कॉलेज मिल सकता है?", HINDI),
    ("IIT Delhi में JEE rank कितनी चाहिए?", HINDI),   # Hindi with English names is Hindi
    ("What does शिक्षा mean in this sentence here?", ENGLISH),  # one quoted word is not
    ("", ENGLISH),
])
def test_language_of_text(text, expected):
    assert language_of_text(text) == expected


@pytest.mark.parametrize("name, expected", [
    ("hindi", HINDI), ("Urdu", HINDI), ("english", ENGLISH), (None, ENGLISH), ("marathi", ENGLISH),
])
def test_language_from_whisper(name, expected):
    assert language_from_whisper(name) == expected


def test_groq_asks_again_for_devanagari_when_hindi_comes_back_in_urdu_script(monkeypatch):
    calls = []

    async def fake_request(self, audio_bytes, filename, language=None):
        calls.append(language)
        if language is None:
            return {"text": "مجھے کالج بتاؤ", "language": "urdu"}
        return {"text": "मुझे कॉलेज बताओ", "language": "hindi"}

    monkeypatch.setattr(GroqWhisperSTT, "_request", fake_request)
    heard = asyncio.run(_groq().transcribe(b"wav", "a.wav"))
    assert (heard.text, heard.language) == ("मुझे कॉलेज बताओ", HINDI)
    assert calls == [None, HINDI]


def test_groq_keeps_english_as_heard(monkeypatch):
    async def fake_request(self, audio_bytes, filename, language=None):
        return {"text": "Tell me about NEET", "language": "english"}

    monkeypatch.setattr(GroqWhisperSTT, "_request", fake_request)
    heard = asyncio.run(_groq().transcribe(b"wav", "a.wav"))
    assert (heard.text, heard.language) == ("Tell me about NEET", ENGLISH)


def _groq():
    return GroqWhisperSTT("https://groq.invalid/openai/v1", "key", "whisper-large-v3")


def test_voice_chat_tells_the_model_to_reply_in_hindi(client, monkeypatch):
    token = client.post("/api/auth/register", json={
        "email": "hindi@maya-device.app", "password": "a-long-password", "name": "Asha", "class_level": 12,
    }).json()["access_token"]
    llm = FakeLLM("ज़रूर, NEET की तैयारी से शुरू करते हैं।")
    monkeypatch.setattr(ai_router, "get_stt_provider", lambda: FakeSTT("मुझे डॉक्टर बनना है", HINDI))
    monkeypatch.setattr(ai_router, "get_tts_provider", lambda: None)
    monkeypatch.setattr(orchestrator, "get_llm_provider", lambda: llm)

    r = client.post("/api/ai/voice-chat", headers={"Authorization": f"Bearer {token}"},
                    files={"audio": ("clip.wav", b"RIFF....WAVE", "audio/wav")})
    assert r.status_code == 200
    body = r.json()
    assert body["language"] == HINDI
    assert body["transcript"] == "मुझे डॉक्टर बनना है"
    # The instruction sits right before the student's message, so it beats earlier turns.
    assert llm.seen[0][-2] == {"role": "system", "content": reply_instruction(LanguageTag(HINDI, DEVANAGARI, 1.0))}
    assert llm.seen[0][-1]["content"] == "मुझे डॉक्टर बनना है"


# ---------------- detecting English / Hindi / Hinglish ----------------

LABELLED = [
    # The spec's own examples (§4, §5, §32)
    ("Mujhe samajh nahi aa raha ki mujhe engineering karni chahiye ya nahi.", HINGLISH),
    ("What are my options if I don't want engineering?", ENGLISH),
    ("Mujhse JEE nahi ho raha, sab friends ka ho raha hai.", HINGLISH),
    ("Mujhe samajh nahi aa raha mujhe kya karna chahiye.", HINGLISH),
    ("I want to continue our career discussion.", ENGLISH),
    ("Mera next step kya hai?", HINGLISH),
    ("Main kitna improve hua hoon?", HINGLISH),
    ("Maine logical reasoning wala step poora kar liya.", HINGLISH),
    ("Agar mujhe AI karna hai toh mere aas paas kaunse colleges hain?", HINGLISH),
    ("Is college mein hostel aur hospital ki facility hai?", HINGLISH),
    # Hinglish typed in English letters
    ("Mujhe doctor banna hai", HINGLISH),
    ("Papa chahte hain main engineering karun", HINGLISH),
    ("PCM lu ya PCB?", HINGLISH),
    ("Maths mein bahut weak hoon yaar", HINGLISH),
    ("Kya main NEET ke bina doctor ban sakta hoon?", HINGLISH),
    ("Coding seekhna hai par kahan se start karun?", HINGLISH),
    ("Mere marks acche nahi aaye", HINGLISH),
    ("Ye college kaisa hai?", HINGLISH),
    ("Bas itna batao ki fees kitni hai", HINGLISH),
    ("Haan theek hai, aage batao", HINGLISH),
    ("Mujhe AI aur robotics dono pasand hain", HINGLISH),
    ("Ghar walon ko kaise samjhaun?", HINGLISH),
    ("Kal se padhai shuru karunga", HINGLISH),
    ("Hostel ka kharcha kitna aata hai?", HINGLISH),
    ("Mera rank 45000 hai, kaunsa NIT milega?", HINGLISH),
    ("Abhi class 10 mein hoon", HINGLISH),
    ("Thoda confused hoon", HINGLISH),
    # English, including the words a Hindi check could trip on
    ("Which colleges can I get with rank 5000?", ENGLISH),
    ("What is the JEE Main cutoff for NIT Trichy?", ENGLISH),
    ("Tell me the main reason to choose PCM.", ENGLISH),
    ("I like biology but I am scared of NEET.", ENGLISH),
    ("How do I log in to the counselling portal?", ENGLISH),
    ("Can you compare IIT Bombay and IIT Delhi?", ENGLISH),
    ("Is there a hostel on campus?", ENGLISH),
    ("I only have two hours a day.", ENGLISH),
    ("Maths is difficult for me.", ENGLISH),
    ("I no longer want AI, I am interested in cybersecurity.", ENGLISH),
    ("What should I do after class 12?", ENGLISH),
    ("My parents want me to be a doctor.", ENGLISH),
    ("How much have I improved?", ENGLISH),
    ("Give me a study plan for physics.", ENGLISH),
    ("Do I need coaching for JEE Advanced?", ENGLISH),
    ("Thank you so much!", ENGLISH),
    ("The fees are too high for my family.", ENGLISH),
    ("What does a data scientist do all day?", ENGLISH),
    # Devanagari (how Whisper writes spoken Hindi)
    ("मुझे कौन सा कॉलेज मिल सकता है?", HINDI),
    ("IIT Delhi में JEE rank कितनी चाहिए?", HINDI),
    ("मुझे डॉक्टर बनना है", HINDI),
    ("मेरा अगला कदम क्या है?", HINDI),
    ("मैं कितना बेहतर हुआ हूँ?", HINDI),
    ("मुझसे जेईई नहीं हो रहा, सब दोस्तों का हो रहा है।", HINDI),
    ("मुझे समझ नहीं आ रहा कि मुझे engineering करनी चाहिए या नहीं", HINDI),
    ("क्या इस कॉलेज में हॉस्टल और अस्पताल की सुविधा है?", HINDI),
    # Devanagari with English mixed in freely: Hinglish
    ("मुझे coding और robotics में interest है", HINGLISH),
    ("अगर मैं computer science लूँ तो options क्या हैं", HINGLISH),
    ("मेरी preparation अच्छी नहीं चल रही", HINGLISH),
]


@pytest.mark.parametrize("text, expected", LABELLED)
def test_detects_the_language(text, expected):
    assert detect(text).lang == expected


def test_the_labelled_set_is_big_enough_to_mean_something():
    assert len(LABELLED) >= 55


@pytest.mark.parametrize("text, script", [
    ("Mera next step kya hai?", LATIN), ("मेरा अगला कदम क्या है?", DEVANAGARI), ("What next?", LATIN),
])
def test_the_script_is_reported(text, script):
    assert detect(text).script == script


def test_a_one_word_reply_keeps_the_conversation_language():
    assert detect("ok", previous=HINGLISH).lang == HINGLISH
    assert detect("ok").lang == ENGLISH
    assert detect("ok").confidence < 0.5


def test_numbers_alone_follow_what_whisper_heard_or_the_habit():
    assert detect("45000", heard=HINDI).lang == HINDI
    assert detect("45000", previous=HINGLISH).lang == HINGLISH


def test_switching_language_mid_conversation_is_followed_at_once():
    # A long, clear English sentence wins over a Hinglish habit.
    assert detect("What are my options if I don't want engineering?", previous=HINGLISH).lang == ENGLISH


@pytest.mark.parametrize("lang, voice", [(ENGLISH, ENGLISH), (HINDI, HINDI), (HINGLISH, HINDI), (None, ENGLISH)])
def test_hindi_and_hinglish_replies_use_the_hindi_voice(lang, voice):
    # Spike S1: Cartesia's English voice mangles Hindi words even when written in English letters.
    assert voice_for(lang) == voice


def test_the_habit_follows_the_latest_turns_and_ignores_one_word_replies():
    stats = None
    for _ in range(3):
        stats = updated_stats(stats, detect("Mujhe samajh nahi aa raha kya karun"))
    assert usual_language(stats) == HINGLISH
    assert updated_stats(stats, detect("ok")) == stats
    for _ in range(4):
        stats = updated_stats(stats, detect("What are the best colleges for computer science?"))
    assert usual_language(stats) == ENGLISH


def test_roman_hinglish_is_answered_in_roman_hinglish():
    instruction = reply_instruction(detect("Mera next step kya hai?"))
    assert "English letters" in instruction and "Hinglish" in instruction


def test_spoken_hindi_is_answered_in_conversational_devanagari():
    instruction = reply_instruction(detect("मेरा अगला कदम क्या है?"))
    assert "Devanagari" in instruction and "not formal" in instruction


def _register(client, email):
    return client.post("/api/auth/register", json={
        "email": email, "password": "a-long-password", "name": "Ravi", "class_level": 10,
    }).json()["access_token"]


def test_typed_hinglish_gets_a_hinglish_reply_and_says_so(client, monkeypatch, db_session):
    token = _register(client, "hinglish@maya-device.app")
    llm = FakeLLM("Koi baat nahi, chalo milke dekhte hain.")
    monkeypatch.setattr(orchestrator, "get_llm_provider", lambda: llm)
    r = client.post("/api/ai/chat", json={"message": "Mujhe samajh nahi aa raha mujhe kya karna chahiye"},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["language"] == HINGLISH
    assert llm.seen[0][-2]["content"] == reply_instruction(LanguageTag(HINGLISH, LATIN, 1.0))
    from app.models.student import StudentProfile
    assert usual_language(db_session.query(StudentProfile).one().language_stats) is None, "one turn isn't a habit"


def test_speaking_a_hinglish_reply_uses_the_hindi_voice(client, monkeypatch):
    from tests.fakes import FakeTTS
    tts = FakeTTS()
    monkeypatch.setattr(ai_router, "get_tts_provider", lambda: tts)
    token = _register(client, "speak-hinglish@maya-device.app")
    headers = {"Authorization": f"Bearer {token}"}
    client.post("/api/ai/speak", json={"text": "Koi baat nahi, chalo dekhte hain.", "language": HINGLISH}, headers=headers)
    client.post("/api/ai/speak", json={"text": "Let's look at it together."}, headers=headers)
    assert tts.languages == [HINDI, None], "without a language the script decides, as before"
