"""Client for the OpenAI chat-completions format (OpenCode Go, OpenAI, vLLM, Ollama, ...)."""

import logging

import openai

from app.llm.base import LLMError, LLMResult, Message, ToolCall, ToolSpec

log = logging.getLogger(__name__)


class OpenAIChatClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        default_headers: dict[str, str] | None = None,
        session_header: str | None = None,
    ):
        self.model = model
        self._session_header = session_header
        self._client = openai.AsyncOpenAI(
            base_url=base_url, api_key=api_key, default_headers=default_headers, timeout=60, max_retries=2
        )

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        tool_choice: str = "auto",
        session_id: str | None = None,
    ) -> LLMResult:
        request = {
            "model": self.model,
            "messages": [_to_wire(m) for m in messages],
            "temperature": 0.2,
        }
        if tools:
            request["tools"] = [
                {
                    "type": "function",
                    "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
                }
                for t in tools
            ]
            request["tool_choice"] = tool_choice
        if self._session_header and session_id:
            request["extra_headers"] = {self._session_header: session_id}

        try:
            resp = await self._create(request)
        except openai.APIError as e:
            raise LLMError(f"{type(e).__name__}: {e}") from e
        if not resp.choices:
            raise LLMError("Model returned no choices.")

        msg = resp.choices[0].message
        return LLMResult(
            content=msg.content,
            tool_calls=[
                ToolCall(id=tc.id, name=tc.function.name, arguments=tc.function.arguments or "{}")
                for tc in msg.tool_calls or []
            ],
            input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
            output_tokens=resp.usage.completion_tokens if resp.usage else 0,
        )

    async def _create(self, request: dict):
        try:
            return await self._client.chat.completions.create(**request)
        except openai.BadRequestError as e:
            # DeepSeek in thinking mode sometimes rejects a forced tool_choice. Retry unforced;
            # the agent treats a plain-text answer as a reply and still checks its grounding.
            if request.get("tool_choice", "auto") == "auto" or "tool_choice" not in str(e):
                raise
            log.warning("tool_choice=%s rejected upstream, retrying with auto", request["tool_choice"])
            return await self._client.chat.completions.create(**request | {"tool_choice": "auto"})


def _to_wire(m: Message) -> dict:
    wire: dict = {"role": m.role, "content": m.content}
    if m.tool_calls:
        wire["tool_calls"] = [
            {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": tc.arguments}}
            for tc in m.tool_calls
        ]
    if m.tool_call_id:
        wire["tool_call_id"] = m.tool_call_id
    return wire
