"""Counselling sessions: start, talk, end (spec §22, §29) — and the live voice WebSocket.

REST covers typed conversation and session bookkeeping; `WS /api/ws/conversation` streams
spoken turns (docs/design/07-api-contracts.md §2). A session is a `Conversation` row.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai.orchestrator import handle_chat
from app.conversation.session import ConversationSession
from app.memory.lifecycle import remember_soon
from app.memory.opening import opening_line
from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import get_current_student_profile, student_profile_for_token
from app.models.chat import Conversation
from app.models.student import StudentProfile
from app.providers.registry import get_llm_provider
from app.schemas.ai import ChatResponse

router = APIRouter(tags=["conversation"])
logger = logging.getLogger(__name__)
settings = get_settings()


class StartRequest(BaseModel):
    channel: str = "voice"  # voice | text


class StartResponse(BaseModel):
    session_id: int
    # What MAYA opens with when the student returns to something unfinished ("last time we were
    # discussing…") — None for a first session, a quick return, or without memory permission.
    opening: str | None = None


class MessageRequest(BaseModel):
    session_id: int
    text: str


class EndRequest(BaseModel):
    session_id: int


class EndResponse(BaseModel):
    session_id: int
    status: str


def _owned(db: Session, profile: StudentProfile, session_id: int | None) -> Conversation | None:
    if session_id is None:
        return None
    return (db.query(Conversation)
            .filter(Conversation.id == session_id, Conversation.student_profile_id == profile.id).first())


def _start(db: Session, profile: StudentProfile, channel: str) -> Conversation:
    conversation = Conversation(student_profile_id=profile.id, channel=channel)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


@router.post("/api/conversation/start", response_model=StartResponse)
async def start(payload: StartRequest, profile: StudentProfile = Depends(get_current_student_profile),
                db: Session = Depends(get_db)) -> StartResponse:
    conversation = _start(db, profile, payload.channel)
    llm = get_llm_provider()
    opening = await opening_line(db, profile, llm) if llm else None
    return StartResponse(session_id=conversation.id, opening=opening[0] if opening else None)


@router.post("/api/conversation/message", response_model=ChatResponse)
async def message(payload: MessageRequest, profile: StudentProfile = Depends(get_current_student_profile),
                  db: Session = Depends(get_db)) -> ChatResponse:
    if _owned(db, profile, payload.session_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    return await handle_chat(db, profile, payload.text, payload.session_id)


@router.post("/api/conversation/end", response_model=EndResponse)
def end(payload: EndRequest, profile: StudentProfile = Depends(get_current_student_profile),
        db: Session = Depends(get_db)) -> EndResponse:
    conversation = _owned(db, profile, payload.session_id)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    if conversation.status != "closed":
        conversation.status, conversation.ended_at = "closed", datetime.now(timezone.utc)
        db.commit()
        if settings.memory_sweeper:
            remember_soon(conversation.id)  # its memory, in the background
    return EndResponse(session_id=conversation.id, status=conversation.status)


@router.websocket("/api/ws/conversation")
async def conversation_socket(websocket: WebSocket, session_id: int | None = Query(None),
                              token: str | None = Query(None), db: Session = Depends(get_db)) -> None:
    """Auth: the student's token, as `Authorization: Bearer …` or `?token=` (some WebSocket
    clients can't set headers). Resumes `session_id` if it's theirs, else starts a new session."""
    header = websocket.headers.get("authorization", "")
    bearer = header[7:] if header.lower().startswith("bearer ") else None
    profile = student_profile_for_token(db, bearer or token)
    if profile is None:
        await websocket.close(code=4401, reason="Not authenticated")
        return
    await websocket.accept()
    resumed = _owned(db, profile, session_id)
    conversation = resumed if resumed is not None and resumed.status == "open" else _start(db, profile, "voice")
    session = ConversationSession(db, profile, conversation, websocket.send_json, websocket.send_bytes)
    warming = asyncio.create_task(session.warm_up())
    await session.send({"type": "session.ready", "session_id": conversation.id, "opening": None})
    if conversation is not resumed:
        # A new session: if they're coming back to something unfinished, MAYA opens with it.
        # Sent when ready (an LLM call), never holding up the session.
        opening = asyncio.create_task(session.send_opening())
    else:
        opening = None
    try:
        while True:
            frame = await websocket.receive()
            if frame["type"] == "websocket.disconnect":
                break
            if frame.get("bytes") is not None:
                await session.on_bytes(frame["bytes"])
            elif frame.get("text") is not None:
                try:
                    data = json.loads(frame["text"])
                except ValueError:
                    data = None
                if not isinstance(data, dict):
                    await session.send({"type": "error", "code": "bad_message", "message": "expected a JSON object",
                                        "retryable": False})
                    continue
                await session.on_json(data)
    except WebSocketDisconnect:
        pass
    finally:
        warming.cancel()
        if opening is not None:
            opening.cancel()
        await session.close()
        logger.info("conversation %s: connection closed", conversation.id)
