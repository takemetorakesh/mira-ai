import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from app.agent.orchestrator import ConversationNotFound, TurnInProgress, run_turn, turn_payload
from app.agent.state import BookingState
from app.config import get_settings, today
from app.db.models import Conversation, Turn
from app.db.session import get_sessionmaker
from app.llm.factory import get_llm_client

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

# asyncio only keeps weak references to tasks; hold running turns here so a client
# disconnecting mid-stream can't get its turn garbage-collected half way.
_running_turns: set[asyncio.Task] = set()


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@router.get("/health")
async def health() -> dict:
    async with get_sessionmaker()() as s:
        await s.execute(text("SELECT 1"))
    settings = get_settings()
    return {
        "db": "ok",
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "llm_key_set": bool(settings.llm_api_key),
        "today": today().isoformat(),
    }


@router.post("/conversations")
async def create_conversation() -> dict:
    state = BookingState()
    conv = Conversation(id=uuid.uuid4(), state=state.model_dump(mode="json"))
    async with get_sessionmaker()() as s, s.begin():
        s.add(conv)
    return {"id": str(conv.id), "state": state.for_prompt(), "today": today().isoformat()}


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: uuid.UUID) -> dict:
    async with get_sessionmaker()() as s:
        conv = await s.get(Conversation, conversation_id)
        if conv is None:
            raise HTTPException(404, "Conversation not found")
        turns = await s.scalars(select(Turn).where(Turn.conversation_id == conversation_id).order_by(Turn.seq))
        return {
            "id": str(conv.id),
            "state": BookingState.model_validate(conv.state).for_prompt(),
            "today": today().isoformat(),
            "turns": [turn_payload(t) for t in turns],
        }


@router.post("/conversations/{conversation_id}/messages")
async def post_message(conversation_id: uuid.UUID, body: MessageIn) -> StreamingResponse:
    """Runs one turn and streams its trace as server-sent events (tool_call, tool_result, state,
    error), ending with `done`, which carries the reply. The reply is only sent once it has
    passed the grounding check, which is why it isn't streamed token by token."""
    try:
        llm = get_llm_client()
    except ValueError as e:
        raise HTTPException(503, f"LLM not configured: {e}") from e

    events: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue()

    async def emit(event: str, data: dict) -> None:
        await events.put((event, data))

    async def turn() -> None:
        try:
            await run_turn(conversation_id, body.text.strip(), llm, emit)
        except TurnInProgress:
            await emit("fatal", {"status": 409, "message": "Mira is still replying to the previous message."})
        except ConversationNotFound:
            await emit("fatal", {"status": 404, "message": "Conversation not found."})
        except Exception as e:
            log.exception("turn failed")
            await emit("fatal", {"status": 500, "message": f"{type(e).__name__}: {e}"})
        finally:
            await events.put(None)

    task = asyncio.create_task(turn())
    _running_turns.add(task)
    task.add_done_callback(_running_turns.discard)

    async def stream():
        while (item := await events.get()) is not None:
            event, data = item
            yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
