"""Gemini-powered article generation pipeline."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from google import genai
from google.genai import types

from app import prompts
from app.config import Settings
from app.utils import ensure_text, retry_sync

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GeneratedArticle:
    topic_metadata: str
    outline: str
    markdown: str


class BlogGenerator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = genai.Client(api_key=settings.gemini_api_key)

    def generate(self) -> GeneratedArticle:
        logger.info("Generating topic with Gemini")
        topic_metadata = self._generate_text(prompts.topic_prompt())

        logger.info("Generating article outline")
        outline = self._generate_text(prompts.outline_prompt(topic_metadata))

        headings = self._extract_headings(outline)
        if not headings:
            raise ValueError("Could not extract section headings from Gemini outline")

        sections: list[str] = []
        for heading in headings:
            logger.info("Generating section: %s", heading)
            sections.append(
                self._generate_text(prompts.section_prompt(topic_metadata, outline, heading))
            )

        rough_draft = self._merge_article(outline, sections)

        logger.info("Polishing final article")
        final_markdown = self._generate_text(prompts.polish_prompt(rough_draft))

        return GeneratedArticle(
            topic_metadata=topic_metadata,
            outline=outline,
            markdown=final_markdown,
        )

    @retry_sync(attempts=3, initial_delay=2.0)
    def _generate_text(self, prompt: str) -> str:
        response = self.client.models.generate_content(
            model=self.settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.75,
                top_p=0.9,
                max_output_tokens=4096,
            ),
        )
        return ensure_text(response.text)

    @staticmethod
    def _extract_headings(outline: str) -> list[str]:
        headings: list[str] = []
        for line in outline.splitlines():
            stripped = line.strip()
            if re.match(r"^#{2,3}\s+\S", stripped):
                headings.append(re.sub(r"^#{2,3}\s+", "", stripped).strip())
            elif re.match(r"^\d+\.\s+\S", stripped) and BlogGenerator._looks_like_heading(
                stripped
            ):
                headings.append(re.sub(r"^\d+\.\s+", "", stripped).strip())

        cleaned: list[str] = []
        for heading in headings:
            if heading.lower().startswith(("seo title", "description")):
                continue
            if heading not in cleaned:
                cleaned.append(heading)
        return cleaned[:7]

    @staticmethod
    def _looks_like_heading(line: str) -> bool:
        heading = re.sub(r"^\d+\.\s+", "", line).strip()
        if "`" in heading:
            return False
        if len(heading) > 90:
            return False
        if heading.endswith((".", ":", ";")):
            return False
        if heading.lower().startswith(
            (
                "create ",
                "run ",
                "type ",
                "example",
                "analogy",
                "notes",
                "keywords",
            )
        ):
            return False
        return True

    @staticmethod
    def _merge_article(outline: str, sections: list[str]) -> str:
        title = "Generated Technical Article"
        for line in outline.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("seo title"):
                title = stripped.split(":", 1)[-1].strip() or title
                break
            if stripped.startswith("# "):
                title = stripped.removeprefix("# ").strip()
                break

        body = "\n\n".join(section.strip() for section in sections if section.strip())
        return f"# {title}\n\n{body}".strip()
