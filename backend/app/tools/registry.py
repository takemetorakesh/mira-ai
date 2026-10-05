import json
import logging
import time
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from app.llm.base import ToolCall, ToolSpec
from app.tools.addons import GetAddons
from app.tools.availability import CheckAvailability
from app.tools.base import Tool, ToolContext, error
from app.tools.hold import CreateBookingHold
from app.tools.policy import GetPolicy
from app.tools.property_details import GetPropertyDetails
from app.tools.quote import CalculateQuote
from app.tools.respond import Respond
from app.tools.search import SearchProperties
from app.tools.update_state import UpdateBookingState

log = logging.getLogger(__name__)

TOOLS: dict[str, Tool] = {
    t.name: t
    for t in (
        UpdateBookingState(),
        SearchProperties(),
        CheckAvailability(),
        GetPropertyDetails(),
        GetPolicy(),
        GetAddons(),
        CalculateQuote(),
        CreateBookingHold(),
        Respond(),
    )
}


def tool_specs() -> list[ToolSpec]:
    return [ToolSpec(t.name, t.description, json_schema(t.Args)) for t in TOOLS.values()]


@dataclass
class ToolRun:
    args: dict
    result: dict
    status: str  # "ok" | "error"
    ms: int


async def execute(ctx: ToolContext, call: ToolCall) -> ToolRun:
    """Validate and run one tool call.

    Never raises: bad JSON, schema errors and tool bugs come back as error results the model can react to.
    """
    started = time.perf_counter()
    tool = TOOLS.get(call.name)
    args: dict = {}
    try:
        if tool is None:
            result = error("unknown_tool", f"No tool named '{call.name}'.", available=list(TOOLS))
        else:
            args = json.loads(call.arguments or "{}")
            result = await tool.run(ctx, tool.Args.model_validate(args))
    except json.JSONDecodeError as e:
        # Echo what was sent; without it the model tends to repeat the same malformed call.
        result = error("invalid_json", f"Arguments were not valid JSON: {e}", received=call.arguments[:300])
    except ValidationError as e:
        result = error(
            "invalid_arguments",
            "Arguments did not match the schema.",
            details=e.errors(include_url=False, include_context=False),
        )
    except Exception as e:  # a tool bug must not kill the conversation
        log.exception("tool %s failed", call.name)
        result = error("internal_error", f"{call.name} failed unexpectedly: {type(e).__name__}.")
    return ToolRun(
        args=args,
        result=json.loads(json.dumps(result, default=str)),  # dates etc. → JSON-safe for the trace
        status="error" if "error" in result else "ok",
        ms=int((time.perf_counter() - started) * 1000),
    )


def json_schema(model: type[BaseModel]) -> dict:
    """Pydantic schema with $refs inlined; not every OpenAI-compatible backend resolves $defs."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def inline(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return inline(defs[node["$ref"].split("/")[-1]])
            # Titles are noise for the model, and `discriminator` only holds $ref strings.
            return {k: inline(v) for k, v in node.items() if k not in ("title", "discriminator")}
        if isinstance(node, list):
            return [inline(v) for v in node]
        return node

    return inline(schema)
