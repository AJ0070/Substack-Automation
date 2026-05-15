"""Shared utilities for logging, retries, and markdown persistence."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Awaitable, Callable, ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")


def configure_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "automation.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )


def slugify(value: str, fallback: str = "article") -> str:
    value = value.strip().lower()
    value = re.sub(r"^#+\s*", "", value)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value[:80] or fallback


def extract_title(markdown: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped.removeprefix("# ").strip()
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:90]
    return "Untitled Substack Article"


def save_markdown(markdown: str, article_dir: Path) -> Path:
    title = extract_title(markdown)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = article_dir / f"{stamp}-{slugify(title)}.md"
    path.write_text(markdown.strip() + "\n", encoding="utf-8")
    return path


def retry_async(
    attempts: int = 3,
    initial_delay: float = 1.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            delay = initial_delay
            last_error: BaseException | None = None
            for attempt in range(1, attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    last_error = exc
                    if attempt == attempts:
                        break
                    logging.getLogger(func.__module__).warning(
                        "%s failed on attempt %s/%s: %s",
                        func.__name__,
                        attempt,
                        attempts,
                        exc,
                    )
                    await asyncio.sleep(delay)
                    delay *= 2
            assert last_error is not None
            raise last_error

        return wrapper

    return decorator


def retry_sync(
    attempts: int = 3,
    initial_delay: float = 1.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            import time

            delay = initial_delay
            last_error: BaseException | None = None
            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_error = exc
                    if attempt == attempts:
                        break
                    logging.getLogger(func.__module__).warning(
                        "%s failed on attempt %s/%s: %s",
                        func.__name__,
                        attempt,
                        attempts,
                        exc,
                    )
                    time.sleep(delay)
                    delay *= 2
            assert last_error is not None
            raise last_error

        return wrapper

    return decorator


def ensure_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("Gemini returned an empty response")
    return text

