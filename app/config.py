"""Configuration loading and validation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore[assignment]


VALID_PUBLISH_MODES = {"draft", "publish"}


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str
    substack_email: str
    substack_password: str
    publish_mode: str
    substack_publication_url: str
    headless: bool
    article_dir: Path
    log_dir: Path
    gemini_model: str = "gemini-2.5-flash"
    max_retries: int = 6
    gemini_retry_initial_delay_seconds: float = 10.0
    gemini_retry_max_delay_seconds: float = 90.0
    generation_mode: str = "compact"
    playwright_timeout_ms: int = 45_000

    @property
    def should_publish(self) -> bool:
        return self.publish_mode == "publish"


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value or not value.strip():
        raise ValueError(f"Missing required environment variable: {name}")
    return value.strip()


def load_settings(env_file: str | Path = ".env") -> Settings:
    if load_dotenv is not None:
        load_dotenv(env_file)

    publish_mode = os.getenv("PUBLISH_MODE", "draft").strip().lower()
    if publish_mode not in VALID_PUBLISH_MODES:
        raise ValueError(
            f"PUBLISH_MODE must be one of {sorted(VALID_PUBLISH_MODES)}, got {publish_mode!r}"
        )

    article_dir = Path(os.getenv("ARTICLE_DIR", "articles"))
    log_dir = Path(os.getenv("LOG_DIR", "logs"))
    article_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        gemini_api_key=_required("GEMINI_API_KEY"),
        substack_email=_required("SUBSTACK_EMAIL"),
        substack_password=_required("SUBSTACK_PASSWORD"),
        publish_mode=publish_mode,
        substack_publication_url=os.getenv(
            "SUBSTACK_PUBLICATION_URL", "https://substack.com"
        ).rstrip("/"),
        headless=_bool_env("HEADLESS", True),
        article_dir=article_dir,
        log_dir=log_dir,
        max_retries=int(os.getenv("MAX_RETRIES", "6")),
        gemini_retry_initial_delay_seconds=float(
            os.getenv("GEMINI_RETRY_INITIAL_DELAY_SECONDS", "10")
        ),
        gemini_retry_max_delay_seconds=float(
            os.getenv("GEMINI_RETRY_MAX_DELAY_SECONDS", "90")
        ),
        generation_mode=os.getenv("GENERATION_MODE", "compact").strip().lower(),
        playwright_timeout_ms=int(os.getenv("PLAYWRIGHT_TIMEOUT_MS", "45000")),
    )
