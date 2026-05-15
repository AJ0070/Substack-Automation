"""CLI entrypoint for generating and uploading Substack posts."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate and publish a Substack post.")
    parser.add_argument(
        "--skip-publish",
        action="store_true",
        help="Generate and save markdown without uploading to Substack.",
    )
    parser.add_argument(
        "--markdown-file",
        type=Path,
        help="Upload an existing markdown file instead of generating a new article.",
    )
    return parser.parse_args()


async def run() -> None:
    args = parse_args()

    from app.config import load_settings
    from app.generator import BlogGenerator
    from app.publisher import SubstackPublisher
    from app.utils import configure_logging, save_markdown

    settings = load_settings()
    configure_logging(settings.log_dir)

    if args.markdown_file:
        article_path = args.markdown_file
        markdown = article_path.read_text(encoding="utf-8")
        logger.info("Loaded existing article: %s", article_path)
    else:
        article = BlogGenerator(settings).generate()
        markdown = article.markdown
        article_path = save_markdown(markdown, settings.article_dir)
        logger.info("Saved generated article: %s", article_path)

    if args.skip_publish:
        logger.info("Skipping Substack upload because --skip-publish was provided")
        return

    await SubstackPublisher(settings).publish_markdown(markdown, article_path)


if __name__ == "__main__":
    asyncio.run(run())
