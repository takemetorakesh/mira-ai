"""Provider-neutral LLM types. The agent depends only on these; adapters translate to a wire format."""

from dataclasses import dataclass, field
from typing import Literal, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON text as produced by the model; parsed and validated by the executor


@dataclass
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict  # JSON Schema, $refs already inlined


@dataclass
class LLMResult:
    content: str | None
    tool_calls: list[ToolCall]
    input_tokens: int = 0
    output_tokens: int = 0


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    model: str

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        tool_choice: Literal["auto", "required"] = "auto",
        session_id: str | None = None,
    ) -> LLMResult: ...
