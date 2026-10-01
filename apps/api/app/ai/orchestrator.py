"""Chat orchestration (spec §29-31, §61): builds the tool-calling loop around an
`LLMProvider`, persists conversation history, and never lets the model answer factual
college/prediction questions without going through a tool call.
"""

import json

from sqlalchemy.orm import Session

from app.ai.language import REPLY_INSTRUCTIONS, language_of_text
from app.ai.providers import get_llm_provider
from app.ai.tools import TOOL_SPECS, execute_tool
from app.models.chat import Conversation, Message
from app.models.student import StudentProfile
from app.services.student_service import student_track
from app.schemas.ai import ChatResponse

SYSTEM_PROMPT = """You are the AI Career Guide counsellor — a knowledgeable, patient, honest career and \
admissions counsellor for Indian students in Class 8-12, covering JEE, NEET, and other career paths.

Hard rules, no exceptions:
- Never invent facts. Fees, cutoffs, ranks, seat counts, placement statistics, and hostel availability \
must come ONLY from tool calls. If a tool returns no data or an error, tell the student plainly that \
reliable data is currently unavailable for that specific case — do not fall back on general/typical/ \
"historically" phrasing as a substitute for a real number. That phrasing is still a fabrication even when \
it sounds hedged.
- If the student states a rank, percentile, or score directly in their message, use it immediately by \
calling predict_jee / predict_neet / get_cutoffs with that value — do not treat get_exam_profile as a \
prerequisite gate. get_exam_profile only has something to return if the student saved it earlier; a 404 \
or empty result from it does NOT mean "no data exists," it means "check the value they just told you \
instead," or ask for it if they haven't given one.
- If search_colleges finds nothing for a name the student used, try the obvious variations before giving \
up (e.g. drop "IIT/NIT/IIIT" prefixes, try just the city name) — only tell the student you can't find a \
college after that, and ask them to confirm the name rather than guessing which college they meant.
- Never guarantee admission or a career outcome. Predictions are probabilistic estimates based on \
historical data, not promises. Always frame results with appropriate uncertainty (e.g. "this looks like \
a high-probability option based on past years' cutoffs" not "you will get this seat").
- When you cite a fact from a tool result, mention its verification status if it says "unverified_demo" — \
tell the student this is sample/demo data, not verified real-world information.
- Category (General/EWS/OBC/SC/ST) is only ever used because it is operationally required for admission \
prediction. Never treat it as a signal of a student's ability, and never comment on it beyond what's \
needed to run a prediction.
- For career guidance, never tell a student they "must" pick one path. Present fit levels (strong/moderate/ \
possible) with reasoning, mention alternatives, and let the student (and their parents) decide.
- Ask focused follow-up questions to fill in missing information (rank, category, preferences) rather than \
assuming defaults, but don't re-ask for anything you can already see in get_student_profile / \
get_exam_profile.
- Keep answers concise, warm, and free of unexplained jargon.
- You speak English and Hindi. Always answer in the language the student is using right now \
(each message carries a note saying which).
"""

MAX_TOOL_ITERATIONS = 5


def _get_or_create_conversation(db: Session, profile: StudentProfile, conversation_id: int | None) -> Conversation:
    if conversation_id:
        conv = (
            db.query(Conversation)
            .filter(Conversation.id == conversation_id, Conversation.student_profile_id == profile.id)
            .first()
        )
        if conv:
            return conv
    conv = Conversation(student_profile_id=profile.id)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


TRACK_RULES = {
    "medical": (
        "This student is preparing for NEET (medicine). Keep suggestions on that track: medical "
        "colleges, MBBS/BDS/AYUSH courses, biology-side subjects and careers. Do not offer JEE, "
        "engineering colleges, or B.Tech branches unless the student asks about them or says they "
        "are reconsidering — if they do ask, answer properly."
    ),
    "engineering": (
        "This student is preparing for JEE (engineering). Keep suggestions on that track: engineering "
        "colleges, B.Tech branches, maths-side subjects and careers. Do not offer NEET or medical "
        "options unless the student asks about them or says they are reconsidering — if they do ask, "
        "answer properly."
    ),
}


def _student_context(profile: StudentProfile) -> str:
    """What MAYA already knows, so she doesn't have to ask (or guess) the basics — above all
    which exam the student picked, which is what keeps her off the wrong track."""
    known = [f"Name: {profile.name}", f"Class: {profile.class_level}"]
    for label, value in (
        ("Board", profile.school_board), ("State", profile.state),
        ("Domicile state", profile.domicile_state), ("Category", profile.category),
    ):
        if value:
            known.append(f"{label}: {value}")
    lines = ["About the student you are talking to:", *(f"- {k}" for k in known)]

    track = student_track(profile)
    if profile.target_exam_code and profile.target_exam_code != "careers":
        lines.append(f"- Target exam: {profile.target_exam_code}")
    if track:
        lines.append(TRACK_RULES[track])
    elif profile.knows_career_goal is False:
        lines.append(
            "This student hasn't chosen a direction yet. Explore options broadly with them — across "
            "engineering, medicine, and other paths — instead of assuming one."
        )
    return "\n".join(lines)


def _history_as_messages(conversation: Conversation, profile: StudentProfile) -> list[dict]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT + "\n\n" + _student_context(profile)}]
    for m in conversation.messages[-20:]:
        if m.role in ("user", "assistant"):
            messages.append({"role": m.role, "content": m.content})
    return messages


async def handle_chat(
    db: Session, profile: StudentProfile, message: str, conversation_id: int | None,
    language: str | None = None,
) -> ChatResponse:
    """language: what the student spoke in, when known from speech ("en"/"hi"); typed
    messages are judged by their script."""
    conversation = _get_or_create_conversation(db, profile, conversation_id)

    llm = get_llm_provider()
    if llm is None:
        db.add(Message(conversation_id=conversation.id, role="user", content=message))
        db.commit()
        return ChatResponse(
            conversation_id=conversation.id,
            reply=(
                "The AI assistant isn't configured yet — an OPENROUTER_API_KEY is needed on the server. "
                "The rest of the app (profile, predictions, colleges) works without it."
            ),
            tool_calls_used=[],
            ai_configured=False,
        )

    messages = _history_as_messages(conversation, profile)
    messages.append({"role": "system", "content": REPLY_INSTRUCTIONS[language or language_of_text(message)]})
    messages.append({"role": "user", "content": message})
    db.add(Message(conversation_id=conversation.id, role="user", content=message))
    db.commit()

    tool_calls_used: list[str] = []
    final_content = ""

    for _ in range(MAX_TOOL_ITERATIONS):
        response = await llm.chat(messages, tools=TOOL_SPECS)
        tool_calls = response.get("tool_calls")

        if not tool_calls:
            final_content = response.get("content") or "I don't have a response for that right now."
            break

        messages.append(
            {
                "role": "assistant",
                "content": response.get("content") or "",
                "tool_calls": tool_calls,
            }
        )
        for call in tool_calls:
            fn_name = call["function"]["name"]
            try:
                fn_args = json.loads(call["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                fn_args = {}
            result = execute_tool(db, profile, fn_name, fn_args)
            tool_calls_used.append(fn_name)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(result, default=str),
                }
            )
    else:
        final_content = "I gathered some information but couldn't finish reasoning about it — could you rephrase or narrow your question?"

    db.add(Message(conversation_id=conversation.id, role="assistant", content=final_content))
    db.commit()

    return ChatResponse(
        conversation_id=conversation.id,
        reply=final_content,
        tool_calls_used=tool_calls_used,
        ai_configured=True,
    )
