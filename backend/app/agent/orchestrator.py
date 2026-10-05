"""Runs one guest turn.

Lock the conversation, build the prompt from rules + booking state + recent turns, then loop:
the model calls tools, we run them and feed results back, until it calls `respond`. The reply
is grounding-checked (one retry) before the turn and the new state are saved together.
"""

import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.grounding import check_reply
from app.agent.state import BookingState, diff
from app.config import get_settings, today
from app.db import repo
from app.db.models import Conversation, Turn
from app.db.session import get_sessionmaker
from app.llm.base import LLMClient, LLMError, Message, ToolCall
from app.tools.base import ToolContext
from app.tools.registry import execute, tool_specs
from app.tools.respond import NextAction, RespondArgs

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system.md").read_text()
LEDGER_TURNS = 2  # tool results from this many previous turns can still be quoted
MAX_GROUNDING_RETRIES = 1
FALLBACK_REPLY = (
    "Sorry, I want to be sure I give you accurate details. "
    "Let me check this with the property team and get back to you shortly."
)
LOCK_NOT_AVAILABLE = "55P03"

Emit = Callable[[str, dict], Awaitable[None]]


class TurnInProgress(Exception):
    pass


class ConversationNotFound(Exception):
    pass


@dataclass
class TurnOutcome:
    reply: str
    next_action: str


async def run_turn(conversation_id: uuid.UUID, text: str, llm: LLMClient, emit: Emit) -> dict:
    settings = get_settings()
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as s, s.begin():
        conv = await _lock_conversation(s, conversation_id)
        recent = await _recent_turns(s, conversation_id, settings.history_turns)
        state = BookingState.model_validate(conv.state)
        initial = state.model_copy(deep=True)
        ctx = ToolContext(
            session=s,
            sessionmaker=sessionmaker,
            state=state,
            conversation_id=conversation_id,
            turn_seq=recent[-1].seq + 1 if recent else 1,
            today=today(),
            settings=settings,
        )

        agent = AgentTurn(ctx, llm, emit)
        outcome = await agent.run(text, recent)

        turn = Turn(
            conversation_id=conversation_id,
            seq=ctx.turn_seq,
            user_message=text,
            reply=outcome.reply,
            tool_calls=agent.tool_calls,
            state_diff=diff(initial, ctx.state),
            next_action=outcome.next_action,
            errors=agent.errors,
        )
        s.add(turn)
        conv.state = ctx.state.model_dump(mode="json")

    payload = turn_payload(turn) | {"state": ctx.state.for_prompt()}
    await emit("done", payload)
    return payload


async def _lock_conversation(s: AsyncSession, conversation_id: uuid.UUID) -> Conversation:
    # FOR NO KEY UPDATE rather than FOR UPDATE: it still serializes turns, but doesn't block the
    # hold tool's separate transaction from inserting a row that references this conversation.
    query = select(Conversation).where(Conversation.id == conversation_id).with_for_update(nowait=True, key_share=True)
    try:
        conv = (await s.execute(query)).scalar_one_or_none()
    except DBAPIError as e:
        if getattr(e.orig, "sqlstate", None) == LOCK_NOT_AVAILABLE:
            raise TurnInProgress() from e
        raise
    if conv is None:
        raise ConversationNotFound()
    return conv


async def _recent_turns(s: AsyncSession, conversation_id: uuid.UUID, limit: int) -> list[Turn]:
    query = select(Turn).where(Turn.conversation_id == conversation_id).order_by(Turn.seq.desc()).limit(limit)
    return list(reversed((await s.scalars(query)).all()))


class AgentTurn:
    """The tool-calling loop for a single guest message, plus everything it records on the way."""

    def __init__(self, ctx: ToolContext, llm: LLMClient, emit: Emit):
        self.ctx = ctx
        self.llm = llm
        self.emit = emit
        self.tool_calls: list[dict] = []
        self.errors: list[dict] = []
        self._ledger: list[str] = []  # facts the reply may use
        self._room_names: list[str] = []
        self._results_by_call: dict[tuple[str, str], dict] = {}
        self._hold_created = False
        self._grounding_retries = 0

    async def run(self, text: str, recent: list[Turn]) -> TurnOutcome:
        messages = await self._build_messages(text, recent)
        specs = tool_specs()
        respond_only = [spec for spec in specs if spec.name == "respond"]
        max_steps = self.ctx.settings.max_agent_steps

        # max_steps calls for tools, then up to two reply-only calls: the second gives a malformed or
        # ungrounded final reply one more try. (DeepSeek rejects naming a tool in tool_choice, so we
        # narrow the tool list instead.)
        for step in range(max_steps + 1):
            reply_only = step >= max_steps - 1
            try:
                res = await self.llm.complete(
                    messages,
                    respond_only if reply_only else specs,
                    tool_choice="required",
                    session_id=str(self.ctx.conversation_id),
                )
            except LLMError as e:
                await self._error("llm_error", str(e))
                break

            calls, content = res.tool_calls, res.content
            if not calls and content:
                # A plain-text answer is treated as `respond`, so it still gets grounding-checked.
                calls, content = [_respond_call(content)], None
            if not calls:
                await self._error("empty_response", "Model returned neither tool calls nor text.")
                continue
            messages.append(Message("assistant", content, tool_calls=calls))

            outcome = None
            for call in calls:
                if call.name == "respond":
                    result, outcome = await self._respond(call, alone=len(calls) == 1)
                else:
                    result = await self._run_tool(call)
                messages.append(Message("tool", json.dumps(result, ensure_ascii=False), tool_call_id=call.id))
            if outcome:
                return outcome

        await self._error("no_reply", "No grounded reply within the step limit.")
        return TurnOutcome(FALLBACK_REPLY, NextAction.handoff_to_staff)

    async def _build_messages(self, text: str, recent: list[Turn]) -> list[Message]:
        properties = await repo.property_index(self.ctx.session)
        self._room_names = await repo.room_names(self.ctx.session)
        index = "\n".join(f"- {p.id}: {p.name}, {p.area}, {p.city}" for p in properties)
        system = SYSTEM_PROMPT.format(
            today=self.ctx.today.isoformat(),
            weekday=f"{self.ctx.today:%A}",
            cities=", ".join(sorted({p.city for p in properties})),
            properties=index,
            state=json.dumps(self.ctx.state.for_prompt(), ensure_ascii=False),
        )

        self._ledger = [index, text]
        for t in recent[-LEDGER_TURNS:]:
            self._ledger += [json.dumps(c["result"], ensure_ascii=False) for c in t.tool_calls]

        messages = [Message("system", system)]
        for t in recent:
            messages += [Message("user", t.user_message), Message("assistant", t.reply)]
        messages.append(Message("user", text))
        return messages

    async def _run_tool(self, call: ToolCall) -> dict:
        key = (call.name, json.dumps(_parse_args(call.arguments), sort_keys=True))
        if key in self._results_by_call and call.name != "update_booking_state":
            # Small models sometimes repeat the same lookup until they run out of steps.
            return self._results_by_call[key] | {"note": "You already have this result. Use it and move on."}

        await self.emit("tool_call", {"id": call.id, "name": call.name, "arguments": _parse_args(call.arguments)})
        state_before = self.ctx.state.model_copy(deep=True)
        run = await execute(self.ctx, call)

        entry = {
            "id": call.id,
            "name": call.name,
            "args": run.args,
            "result": run.result,
            "status": run.status,
            "ms": run.ms,
        }
        self.tool_calls.append(entry)
        self._results_by_call[key] = run.result
        self._ledger.append(json.dumps(run.result, ensure_ascii=False))
        if call.name == "create_booking_hold" and run.status == "ok":
            self._hold_created = True

        await self.emit("tool_result", entry)
        if changes := diff(state_before, self.ctx.state):
            await self.emit("state", {"state": self.ctx.state.for_prompt(), "changes": changes})
        return run.result

    async def _respond(self, call: ToolCall, alone: bool) -> tuple[dict, TurnOutcome | None]:
        """Returns the tool result to show the model, and the outcome if the turn is finished."""
        if not alone:
            return {
                "error": "respond_not_alone",
                "message": "Call respond on its own, after reading the other results.",
            }, None
        try:
            args = RespondArgs.model_validate_json(call.arguments)
        except ValidationError as e:
            await self._error("invalid_reply", str(e)[:300], received=call.arguments[:300])
            return {"error": "invalid_arguments", "message": str(e)[:300], "received": call.arguments[:300]}, None

        ledger = "\n".join([*self._ledger, json.dumps(self.ctx.state.for_prompt(), ensure_ascii=False)])
        violations = check_reply(args.message, ledger, self._room_names, self._hold_created)
        if not violations:
            return {"ok": True}, TurnOutcome(args.message, args.next_action)

        await self._error("grounding", violations=violations, rejected_reply=args.message)
        if self._grounding_retries < MAX_GROUNDING_RETRIES:
            self._grounding_retries += 1
            message = "Rewrite the reply using only facts from tool results, or call a tool first."
            return {"error": "grounding_failed", "violations": violations, "message": message}, None
        return {"ok": True}, TurnOutcome(FALLBACK_REPLY, NextAction.handoff_to_staff)

    async def _error(self, kind: str, message: str | None = None, **details) -> None:
        err = {"kind": kind, **({"message": message} if message else {}), **details}
        self.errors.append(err)
        await self.emit("error", err)


def _respond_call(text: str) -> ToolCall:
    args = json.dumps({"message": text, "next_action": NextAction.answer_question})
    return ToolCall(id=f"text-{uuid.uuid4().hex[:8]}", name="respond", arguments=args)


def _parse_args(raw: str):
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


def turn_payload(t: Turn) -> dict:
    return {
        "seq": t.seq,
        "user_message": t.user_message,
        "reply": t.reply,
        "next_action": str(t.next_action),
        "tool_calls": t.tool_calls,
        "state_diff": t.state_diff,
        "errors": t.errors,
    }
