"""Configuration loaded from .env (secrets) with sensible defaults.

Runtime-tweakable settings (thresholds, cache age, test inbox...) live in the
`settings` table instead - see db.py.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# OpenAI-compatible providers. Switching provider = change LLM_PROVIDER in .env.
PROVIDERS = {
    "groq": {"base_url": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY"},
    "openai": {"base_url": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY"},
}
DEFAULT_MODEL = {
    # Groq's lineup changes often - run `python -m scripts.check_llm` to see
    # what your key can use, then set LLM_MODEL in .env.
    "groq": "llama-3.3-70b-versatile",
    "openai": "gpt-4o-mini",
}


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    llm_provider: str
    llm_base_url: str
    llm_api_key: str | None
    llm_model: str
    data_dir: Path
    db_path: Path
    test_mode: bool
    test_inbox: str | None
    serper_api_key: str | None = None
    http_min_interval: float = 1.0   # seconds between requests to the same website

    @property
    def llm_key_masked(self) -> str:
        if not self.llm_api_key:
            return "(missing)"
        return self.llm_api_key[:4] + "…" + self.llm_api_key[-4:]


def load_config() -> Config:
    provider = os.getenv("LLM_PROVIDER", "groq").strip().lower()
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown LLM_PROVIDER '{provider}'. Use one of: {', '.join(PROVIDERS)}")
    p = PROVIDERS[provider]

    # Keep the live database OUTSIDE OneDrive: sync can lock/corrupt SQLite files.
    data_dir = Path(os.getenv("DATA_DIR") or (Path.home() / "doctor_data")).expanduser()
    db_path = Path(os.getenv("DB_PATH") or (data_dir / "leads.db")).expanduser()

    key = (os.getenv(p["key_env"]) or "").strip() or None
    return Config(
        llm_provider=provider,
        llm_base_url=os.getenv("LLM_BASE_URL", p["base_url"]),
        llm_api_key=key,
        llm_model=os.getenv("LLM_MODEL", DEFAULT_MODEL[provider]),
        data_dir=data_dir,
        db_path=db_path,
        test_mode=_bool(os.getenv("TEST_MODE"), True),  # safe default: ON
        test_inbox=(os.getenv("TEST_INBOX") or "").strip() or None,
        serper_api_key=(os.getenv("SERPER_API_KEY") or "").strip() or None,
        http_min_interval=float(os.getenv("HTTP_MIN_INTERVAL", "1.0")),
    )
