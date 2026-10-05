import base64
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.ai.language import voice_for
from app.ai.orchestrator import handle_chat
from app.core.db import get_db
from app.core.deps import get_current_student_profile, require_local_or_authenticated
from app.core.ratelimit import limit
from app.models.chat import Conversation
from app.models.student import StudentProfile
from app.providers.registry import get_stt_provider, get_tts_provider
from app.schemas.ai import (
    ChatMessageOut, ChatRequest, ChatResponse, SpeakRequest, SpeakResponse, TranscribeResponse, VoiceChatResponse,
)

router = APIRouter(prefix="/api/ai", tags=["ai"])
logger = logging.getLogger(__name__)

# Keep spoken replies shorter than the full text reply — good voice-assistant UX, and
# considerate of TTS provider credit costs for long paragraphs.
MAX_SPEECH_CHARS = 500


async def _synthesize(text: str, language: str | None = None) -> tuple[str | None, str | None]:
    """language: the reply's ("en"/"hi"/"hinglish"); None lets the script decide."""
    tts = get_tts_provider()
    if tts is None:
        return None, None
    speech_text = text if len(text) <= MAX_SPEECH_CHARS else text[:MAX_SPEECH_CHARS].rsplit(" ", 1)[0] + "…"
    try:
        result = await tts.synthesize(speech_text, voice_for(language) if language else None)
    except Exception as e:  # noqa: BLE001 — e.g. bad key or no credits; text-only must still work
        # Logged because with no fallback voice, this is the only trace of why MAYA went quiet.
        logger.warning("TTS failed, replying without audio: %s", e)
        return None, None
    if result is None:
        return None, None
    audio_bytes, content_type = result
    return base64.b64encode(audio_bytes).decode("ascii"), content_type


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(limit("ai"))])
async def chat(
    payload: ChatRequest,
    profile: StudentProfile = Depends(get_current_student_profile),
    db: Session = Depends(get_db),
) -> ChatResponse:
    return await handle_chat(db, profile, payload.message, payload.conversation_id)


@router.post("/voice-chat", response_model=VoiceChatResponse, dependencies=[Depends(limit("ai"))])
async def voice_chat(
    audio: UploadFile = File(...),
    conversation_id: int | None = None,
    profile: StudentProfile = Depends(get_current_student_profile),
    db: Session = Depends(get_db),
) -> VoiceChatResponse:
    stt = get_stt_provider()
    if stt is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Voice input isn't configured yet — a GROQ_API_KEY is needed on the server.",
        )

    heard = await stt.transcribe(await audio.read(), audio.filename or "audio.webm")
    chat_response = await handle_chat(db, profile, heard.text, conversation_id, language=heard.language)
    audio_base64, audio_content_type = await _synthesize(chat_response.reply, chat_response.language)

    return VoiceChatResponse(
        **chat_response.model_dump(),
        transcript=heard.text,
        audio_base64=audio_base64,
        audio_content_type=audio_content_type,
    )


@router.post("/transcribe", response_model=TranscribeResponse, dependencies=[Depends(limit("ai"))])
async def transcribe(
    audio: UploadFile = File(...),
    _: None = Depends(require_local_or_authenticated),
) -> TranscribeResponse:
    """Speech-to-text only, no chat pipeline — for filling a form field by voice (the
    first-boot name/class questions, dictating into any text box)."""
    stt = get_stt_provider()
    if stt is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Voice input isn't configured yet — a GROQ_API_KEY is needed on the server.",
        )
    heard = await stt.transcribe(await audio.read(), audio.filename or "audio.wav")
    return TranscribeResponse(transcript=heard.text.strip())


@router.post("/speak", response_model=SpeakResponse, dependencies=[Depends(limit("ai"))])
async def speak(
    payload: SpeakRequest,
    _: None = Depends(require_local_or_authenticated),
) -> SpeakResponse:
    """Lets MAYA speak any text aloud — replies, the boot greeting, questions she asks
    before any account exists. Never fails the caller if TTS is unavailable; it just
    returns null audio and the caller falls back to on-screen text."""
    audio_base64, audio_content_type = await _synthesize(payload.text, payload.language)
    return SpeakResponse(
        audio_base64=audio_base64, audio_content_type=audio_content_type,
        tts_configured=get_tts_provider() is not None,
    )


@router.get("/conversations/{conversation_id}", response_model=list[ChatMessageOut])
def get_conversation(
    conversation_id: int,
    profile: StudentProfile = Depends(get_current_student_profile),
    db: Session = Depends(get_db),
) -> list[ChatMessageOut]:
    conv = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.student_profile_id == profile.id)
        .first()
    )
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conv.messages
