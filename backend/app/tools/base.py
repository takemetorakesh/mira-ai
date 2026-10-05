import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, ClassVar

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.state import BookingState
from app.config import Settings


@dataclass
class ToolContext:
    session: AsyncSession  # the turn's transaction (reads + final state write)
    sessionmaker: async_sessionmaker  # for writes that must commit independently (holds)
    state: BookingState  # tools mutate this; the orchestrator persists it at the end of the turn
    conversation_id: uuid.UUID
    turn_seq: int
    today: date
    settings: Settings


class Tool:
    name: ClassVar[str]
    description: ClassVar[str]
    Args: ClassVar[type[BaseModel]]

    async def run(self, ctx: ToolContext, args: Any) -> dict:
        raise NotImplementedError


def error(code: str, message: str, **extra) -> dict:
    """Tool failures are results, not exceptions: the model reads them and adapts."""
    return {"error": code, "message": message, **extra}


def missing_trip_fields(state: BookingState) -> dict | None:
    missing = state.missing_for_search()
    if missing:
        return error("missing_fields", "Ask the guest for these before searching or pricing.", fields=missing)
    return None
