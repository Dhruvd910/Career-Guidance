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


class VoiceChatResponse(ChatResponse):
    transcript: str
    language: str = "en"  # what the student spoke: "en" or "hi"
    audio_base64: str | None = None
    audio_content_type: str | None = None


class SpeakRequest(BaseModel):
    text: str


class SpeakResponse(BaseModel):
    audio_base64: str | None
    audio_content_type: str | None
    tts_configured: bool


class TranscribeResponse(BaseModel):
    transcript: str
