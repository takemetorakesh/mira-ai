from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
IST = ZoneInfo("Asia/Kolkata")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://localhost:5432/mira"
    llm_provider: str = "opencode_go"
    llm_api_key: str = ""
    llm_model: str = "deepseek-v4.1-flash"
    llm_base_url: str | None = None
    mira_today: date | None = None
    hold_ttl_minutes: int = 15
    max_agent_steps: int = 6
    history_turns: int = 8


EVAL_DATABASE = "mira_eval"


def eval_database_url(url: str | None = None) -> str:
    """Same server and credentials as DATABASE_URL, but the isolated eval/test database."""
    url = url or Settings().database_url
    return url.rsplit("/", 1)[0] + "/" + EVAL_DATABASE


@lru_cache
def get_settings() -> Settings:
    return Settings()


def today() -> date:
    """The date relative expressions are resolved against. Frozen via MIRA_TODAY for evals/demos."""
    return get_settings().mira_today or datetime.now(IST).date()
