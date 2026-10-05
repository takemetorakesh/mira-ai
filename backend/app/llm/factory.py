"""Provider factory. Switching provider or model is configuration only (LLM_PROVIDER, LLM_MODEL,
LLM_BASE_URL, LLM_API_KEY). A provider with a different wire format needs one new adapter class."""

from functools import lru_cache

from app.config import Settings, get_settings
from app.llm.base import LLMClient
from app.llm.openai_chat import OpenAIChatClient

USER_AGENT = "mira-agent/0.1"

PRESETS = {
    # OpenCode Go asks clients to identify themselves and send a stable per-conversation session id.
    "opencode_go": {"base_url": "https://opencode.ai/zen/go/v1", "session_header": "x-opencode-session"},
    "openai": {"base_url": "https://api.openai.com/v1", "session_header": None},
    "openai_compatible": {"base_url": None, "session_header": None},
}


def create_llm_client(settings: Settings) -> LLMClient:
    preset = PRESETS.get(settings.llm_provider)
    if preset is None:
        raise ValueError(f"Unknown LLM_PROVIDER '{settings.llm_provider}'. Options: {', '.join(PRESETS)}")
    base_url = settings.llm_base_url or preset["base_url"]
    if not base_url:
        raise ValueError(f"LLM_PROVIDER={settings.llm_provider} requires LLM_BASE_URL.")
    if not settings.llm_api_key:
        raise ValueError("LLM_API_KEY is not set.")
    return OpenAIChatClient(
        base_url=base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        default_headers={"User-Agent": USER_AGENT},
        session_header=preset["session_header"],
    )


@lru_cache
def get_llm_client() -> LLMClient:
    """One shared client per process, so HTTP connections to the provider are reused."""
    return create_llm_client(get_settings())
