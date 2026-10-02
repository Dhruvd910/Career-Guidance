"""Chat orchestration (spec §29-31, §61): builds the tool-calling loop around an
`LLMProvider`, persists conversation history, and never lets the model answer factual
college/prediction questions without going through a tool call.
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.ai.language import detect, reply_instruction, updated_stats, usual_language
from app.ai.money_guard import Guard
from app.ai import safety
from app.ai.tools import TOOL_SPECS, execute_tool
from app.assessment.context import assessment_context
from app.roadmap.context import roadmap_context
from app.memory.retrieval import build_memory_context
from app.memory.state import schedule_analysis, tone_note
from app.providers.llm import LLMProvider, TextDelta, ToolCall
from app.providers.registry import get_embedding_provider, get_llm_provider
from app.models.chat import Conversation, Message
from app.models.student import StudentProfile
from app.services.student_service import student_track
from app.schemas.ai import ChatResponse

SYSTEM_PROMPT = """You are MAYA, the AI Career Guide counsellor — a knowledgeable, patient, honest career and \
admissions counsellor for Indian students in Class 8-12, covering JEE, NEET, and other career paths. When you \
introduce yourself, you are MAYA.

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
- For career guidance, never tell a student they "must" pick one path, and never present one career as \
"the" answer. Use their assessment results and career directions (strong / potential / needs exploration), \
give the reasons behind them (explain_direction), mention alternatives, and let the student (and their \
parents) decide. Assessments show how they did on the day, not a fixed ability — say "your answers suggest", \
not "you are". If they haven't taken one and are unsure what suits them, offer it with suggest_assessment \
rather than guessing their strengths. For "how much have I improved", use compare_assessments and call a \
change an improvement only when it says so.
- How to get into a career (streams, subjects, exams, degrees), what to learn for it, which careers a stream \
keeps open, and which colleges offer it come only from career_pathways, career_skills, what_stays_open and \
colleges_offering — never from your own memory, however well you think you know it (call the tool even for \
doctor, lawyer or IAS).
- What a college costs, its hostel and medical facility, where it is and what's near it, its NIRF rank and \
admission dates come only from college_facts, find_colleges and admission_dates; what official documents say \
about rules and eligibility, from search_documents. Say where each value comes from and how fresh it is ("per \
NIT Trichy's 2026-27 fee notice, checked 3 days ago"); for a stale one say "as of <date>"; for anything not \
there, say you couldn't verify it — never estimate a fee, a distance or a date. Never call a college the best: \
offer to compare the attributes that matter to the student (distance, fees, hostel, NIRF rank).
- The student's plan, its next step and their progress come only from the roadmap tools. When their situation \
changes ("I only have two hours a day", "maths is hard", "I like cybersecurity now"), call adjust_roadmap with \
save false to see what would change, tell them briefly and ask whether to do it. After they agree, call it with \
save true and explain what changed and why — finished work still counts and old versions are kept. When they \
say they've finished or started a step, record it with update_roadmap_progress straight away. Never say the \
roadmap or a step has changed unless a roadmap tool has just returned that.
- Ask focused follow-up questions to fill in missing information (rank, category, preferences) rather than \
assuming defaults, but don't re-ask for anything you can already see in get_student_profile / \
get_exam_profile.
- Keep answers concise, warm, and free of unexplained jargon.
- Everything you say is read aloud by MAYA's voice. Talk like a person, not a document: usually two to \
four short sentences, no markdown, no bullet or numbered lists, no tables. If there is more to cover, give \
the most useful part, then offer to go on or ask a question that narrows it down.
- If a student says anything suggesting they might hurt themselves, end their life, or that someone is \
hurting them: career talk stops. Respond with care, don't diagnose, encourage a trusted adult, and give \
Tele-MANAS 14416 (free, 24x7) — and Childline 1098 for abuse, 112 in an emergency.
- You are female: in Hindi and Hinglish use feminine forms for yourself ("samajh gayi", "main batati hoon", \
"kar sakti hoon"), never masculine ones ("samajh gaya", "batata hoon").
- Don't guess the student's gender from their name. In Hindi and Hinglish, talk to them in forms that don't \
assume one ("aap kya karna chahenge?", "tum kya karna chahte ho?"), unless they've told you.
- You speak English, Hindi and Hinglish. Always answer in the language the student is using right now \
(each message carries a note saying which), and switch whenever they do.
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


# Roughly 2,500 tokens of earlier conversation; older turns drop out first.
HISTORY_BUDGET_CHARS = 10_000
INTERRUPTED_NOTE = " [The student interrupted you here; they did not hear the rest.]"


def _history_as_messages(conversation: Conversation, profile: StudentProfile) -> list[dict]:
    earlier: list[dict] = []
    used = 0
    for m in reversed(conversation.messages):
        if m.role not in ("user", "assistant"):
            continue
        content = m.content + (INTERRUPTED_NOTE if m.interrupted else "")
        if earlier and used + len(content) > HISTORY_BUDGET_CHARS:
            break
        used += len(content)
        earlier.append({"role": m.role, "content": content})
    system = {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + _student_context(profile)}
    return [system, *reversed(earlier)]


@dataclass(frozen=True)
class ToolActivity:
    """MAYA is looking something up — the moment to say "let me check"."""

    name: str


@dataclass(frozen=True)
class UiSuggestion:
    """Something for the student's screen to offer — e.g. a button to start an assessment."""

    data: dict


class Reply:
    """One reply to one student message, generated as a stream.

    Iterate events() for the reply's text as it's written (str pieces), a ToolActivity
    whenever a tool runs, and a UiSuggestion when one offers the screen something; afterwards
    `text` is the whole reply, `tool_calls_used` what it looked up and `suggestions` what it
    offered. Build it before saving the student's message: the history it sends is everything
    said *before* this message, which it then adds itself.
    """

    def __init__(self, db: Session, profile: StudentProfile, conversation: Conversation, message: str,
                 heard_language: str | None = None):
        self.db, self.profile = db, profile
        self.tag = detect(message, heard=heard_language, previous=usual_language(profile.language_stats))
        profile.language_stats = updated_stats(profile.language_stats, self.tag)
        self.messages = _history_as_messages(conversation, profile)
        remembered = build_memory_context(db, profile, message, get_embedding_provider())
        if remembered:
            self.messages.insert(1, {"role": "system", "content": remembered})
        self.messages.insert(2 if remembered else 1, {"role": "system", "content": assessment_context(db, profile)})
        self.messages.insert(3 if remembered else 2, {"role": "system", "content": roadmap_context(db, profile)})
        tone = tone_note(db, conversation.id)
        if tone:
            self.messages.append({"role": "system", "content": tone})
        self.messages.append({"role": "system", "content": reply_instruction(self.tag)})
        self.safety = safety.concern(message)
        if self.safety:
            self.messages.append({"role": "system", "content": safety.INSTRUCTION[self.safety]})
        self.messages.append({"role": "user", "content": message})
        # Amounts MAYA may say: ones in this conversation's tool results and the student's own words.
        self.guard = Guard([m["content"] for m in self.messages if m["role"] in ("user", "assistant", "tool")
                            and isinstance(m.get("content"), str)], self.tag.lang)
        self.text = ""
        self.tool_calls_used: list[str] = []
        self.suggestions: list[dict] = []

    def _add(self, piece: str) -> str:
        if self.text and not self.text[-1].isspace() and not piece[:1].isspace():
            piece = " " + piece  # text before a tool call, then the answer after it
        self.text += piece
        return piece

    def _append(self, piece: str) -> str:
        self.text += piece
        return piece

    def _say(self, sentence: str, written: str) -> str:
        # Only the first piece of each round may need a space before it.
        return self._append(sentence) if written else self._add(sentence)

    async def events(self, llm: LLMProvider) -> AsyncIterator[str | ToolActivity | UiSuggestion]:
        for _ in range(MAX_TOOL_ITERATIONS):
            written, calls = "", []
            async for event in llm.stream(self.messages, tools=TOOL_SPECS):
                if isinstance(event, TextDelta) and event.text:
                    for sentence in self.guard.feed(event.text):  # every ₹ amount checked first (P6-11)
                        piece = self._say(sentence, written)
                        written += sentence
                        yield piece
                elif isinstance(event, ToolCall):
                    calls.append(event)
            rest = self.guard.flush()
            if rest:
                piece = self._say(rest, written)
                written += rest
                yield piece
            if not calls:
                return
            self.messages.append({"role": "assistant", "content": written, "tool_calls": [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                for c in calls
            ]})
            for call in calls:
                yield ToolActivity(call.name)
                try:
                    args = json.loads(call.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = execute_tool(self.db, self.profile, call.name, args)
                self.tool_calls_used.append(call.name)
                if isinstance(result, dict) and isinstance(result.get("ui"), dict):
                    ui = result.pop("ui")  # for the screen, not the model
                    self.suggestions.append(ui)
                    yield UiSuggestion(ui)
                content = json.dumps(result, default=str, ensure_ascii=False)
                self.guard.allow(content)  # amounts a tool returned may be said
                self.messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
        yield self._add(GAVE_UP)


GAVE_UP = ("I gathered some information but couldn't finish reasoning about it — could you rephrase or "
           "narrow your question?")
NOT_CONFIGURED = ("The AI assistant isn't configured yet — an OPENROUTER_API_KEY is needed on the server. "
                  "The rest of the app (profile, predictions, colleges) works without it.")


async def handle_chat(
    db: Session, profile: StudentProfile, message: str, conversation_id: int | None,
    language: str | None = None,
) -> ChatResponse:
    """One whole reply, not streamed — for typed chat. language: what Whisper heard, for speech
    ("en"/"hi"); the reply's language is decided from the words themselves (see Reply)."""
    conversation = _get_or_create_conversation(db, profile, conversation_id)
    reply = Reply(db, profile, conversation, message, language)
    said = Message(conversation_id=conversation.id, role="user", content=message, language=reply.tag.lang,
                   modality="voice" if language else "text")
    db.add(said)
    db.commit()

    llm = get_llm_provider()
    schedule_analysis(db, profile, said.id, llm)
    if llm is None:
        return ChatResponse(conversation_id=conversation.id, reply=NOT_CONFIGURED, tool_calls_used=[],
                            ai_configured=False, language=reply.tag.lang)

    async for _ in reply.events(llm):
        pass
    final_content = reply.text.strip() or "I don't have a response for that right now."
    db.add(Message(conversation_id=conversation.id, role="assistant", content=final_content,
                   language=reply.tag.lang))
    db.commit()

    return ChatResponse(
        conversation_id=conversation.id,
        reply=final_content,
        tool_calls_used=reply.tool_calls_used,
        ai_configured=True,
        language=reply.tag.lang,
        suggestions=reply.suggestions,
    )
