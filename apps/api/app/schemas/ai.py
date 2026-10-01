from datetime import datetime

from pydantic import BaseModel


class ChatMessageOut(BaseModel):
    id: int
    role: str
    content: str
    audio_url: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatRequest(BaseModel):
    message: str
    conversation_id: int | None = None


class ChatResponse(BaseModel):
    conversation_id: int
    reply: str
    tool_calls_used: list[str] = []
    ai_configured: bool = True
    # The language the student used and the reply is in: "en", "hi" or "hinglish". Pass it on
    # to /speak so the reply is read with the right voice.
    language: str = "en"


class VoiceChatResponse(ChatResponse):
    transcript: str
    audio_base64: str | None = None
    audio_content_type: str | None = None


class SpeakRequest(BaseModel):
    text: str
    # "en", "hi" or "hinglish" when known (e.g. a chat reply's `language`). Without it the
    # script decides — which reads Hinglish written in English letters with the English voice.
    language: str | None = None


class SpeakResponse(BaseModel):
    audio_base64: str | None
    audio_content_type: str | None
    tts_configured: bool


class TranscribeResponse(BaseModel):
    transcript: str
