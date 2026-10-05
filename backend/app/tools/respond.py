from enum import StrEnum

from pydantic import BaseModel, Field

from app.tools.base import Tool, ToolContext


class NextAction(StrEnum):
    ask_missing_info = "ask_missing_info"
    clarify = "clarify"
    present_options = "present_options"
    answer_question = "answer_question"
    quote_price = "quote_price"
    offer_addons = "offer_addons"
    confirm_hold = "confirm_hold"
    hold_created = "hold_created"
    handoff_to_staff = "handoff_to_staff"


class RespondArgs(BaseModel):
    message: str = Field(
        description="Your reply to the guest. Short, warm, WhatsApp-style plain text. Only facts from tool results."
    )
    next_action: NextAction = Field(description="What this reply is doing to move the booking forward.")


class Respond(Tool):
    """Terminal tool: the orchestrator intercepts it, validates grounding and ends the turn."""

    name = "respond"
    description = "Send your reply to the guest and end your turn. Call exactly once, after any other tools you need."
    Args = RespondArgs

    async def run(self, ctx: ToolContext, args: RespondArgs) -> dict:
        return {"ok": True}
