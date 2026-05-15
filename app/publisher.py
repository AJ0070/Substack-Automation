"""Substack publishing automation using Playwright."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import (
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from app.config import Settings
from app.utils import extract_title, retry_async

logger = logging.getLogger(__name__)


class SubstackPublisher:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def publish_markdown(self, markdown: str, source_path: Path) -> None:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=self.settings.headless)
            try:
                context = await browser.new_context(
                    viewport={"width": 1440, "height": 1100},
                    ignore_https_errors=False,
                )
                context.set_default_timeout(self.settings.playwright_timeout_ms)
                await self._grant_clipboard_permissions(context)
                page = await context.new_page()

                try:
                    await self._login(page)
                    await self._create_post(page, markdown)
                    if self.settings.should_publish:
                        await self._publish(page)
                    else:
                        await self._save_draft(page)
                    logger.info("Substack upload complete for %s", source_path)
                except Exception:
                    await self._capture_failure(page)
                    raise
                finally:
                    await context.close()
            finally:
                await browser.close()

    async def _grant_clipboard_permissions(self, context: BrowserContext) -> None:
        origins = {
            "https://substack.com",
            self.settings.substack_publication_url,
        }
        for origin in origins:
            try:
                await context.grant_permissions(
                    ["clipboard-read", "clipboard-write"], origin=origin
                )
            except PlaywrightError:
                logger.debug("Could not grant clipboard permissions for %s", origin)

    @retry_async(attempts=3, initial_delay=2.0)
    async def _login(self, page: Page) -> None:
        logger.info("Opening Substack login")
        await page.goto("https://substack.com/sign-in", wait_until="domcontentloaded")

        if await self._already_logged_in(page):
            logger.info("Already logged in to Substack")
            return

        await self._fill_first_available(
            page,
            [
                'input[type="email"]',
                'input[name="email"]',
                'input[autocomplete="email"]',
            ],
            self.settings.substack_email,
        )
        await self._click_by_text(page, ["Continue", "Sign in", "Log in"])

        password_filled = await self._try_fill_first_available(
            page,
            [
                'input[type="password"]',
                'input[name="password"]',
                'input[autocomplete="current-password"]',
            ],
            self.settings.substack_password,
        )
        if password_filled:
            await self._click_by_text(page, ["Continue", "Sign in", "Log in"])

        await page.wait_for_load_state("domcontentloaded")
        if await page.locator('input[type="password"]').count():
            raise RuntimeError(
                "Substack login did not complete. Check credentials or two-factor/email-code requirements."
            )

    async def _already_logged_in(self, page: Page) -> bool:
        try:
            await page.goto("https://substack.com/home", wait_until="domcontentloaded")
            return "sign-in" not in page.url and "login" not in page.url
        except PlaywrightError:
            return False

    @retry_async(attempts=3, initial_delay=2.0)
    async def _create_post(self, page: Page, markdown: str) -> None:
        logger.info("Opening new post editor")
        publish_url = f"{self.settings.substack_publication_url}/publish/post"
        await page.goto(publish_url, wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle")

        title = extract_title(markdown)
        body = self._markdown_without_title(markdown)

        await self._fill_title(page, title)
        await self._paste_body(page, body)

    async def _fill_title(self, page: Page, title: str) -> None:
        candidates = [
            'textarea[placeholder*="Title"]',
            'input[placeholder*="Title"]',
            '[contenteditable="true"][data-placeholder*="Title"]',
            '[contenteditable="true"][aria-label*="Title"]',
        ]
        if await self._try_fill_first_available(page, candidates, title):
            return

        textboxes = page.get_by_role("textbox")
        count = await textboxes.count()
        if count:
            await textboxes.first.click()
            await page.keyboard.insert_text(title)
            return

        raise RuntimeError("Could not find Substack title field")

    async def _paste_body(self, page: Page, markdown_body: str) -> None:
        editors = [
            '[contenteditable="true"][data-placeholder*="Write"]',
            '[contenteditable="true"][aria-label*="Body"]',
            '[contenteditable="true"]',
            ".ProseMirror",
        ]

        editor = None
        for selector in editors:
            loc = page.locator(selector)
            if await loc.count():
                editor = loc.last
                break

        if editor is None:
            raise RuntimeError("Could not find Substack body editor")

        await editor.click()
        try:
            await page.evaluate(
                "text => navigator.clipboard.writeText(text)",
                markdown_body,
            )
            await page.keyboard.press("Control+V")
        except PlaywrightError:
            await page.keyboard.insert_text(markdown_body)

        await page.wait_for_timeout(1500)

    @retry_async(attempts=2, initial_delay=2.0)
    async def _save_draft(self, page: Page) -> None:
        logger.info("Saving post as draft")
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2500)

        clicked = await self._try_click_by_text(
            page,
            ["Done", "Save", "Close", "Back to drafts"],
            required=False,
        )
        if not clicked:
            logger.info("No explicit draft save button found; relying on Substack autosave")

    @retry_async(attempts=2, initial_delay=2.0)
    async def _publish(self, page: Page) -> None:
        logger.info("Publishing post")
        await self._click_by_text(page, ["Publish", "Continue"])
        await page.wait_for_timeout(1500)
        await self._try_click_by_text(page, ["Publish now", "Publish", "Send"], required=True)
        await page.wait_for_load_state("networkidle")

    async def _fill_first_available(
        self, page: Page, selectors: list[str], value: str
    ) -> None:
        if not await self._try_fill_first_available(page, selectors, value):
            raise RuntimeError(f"None of these fields were found: {selectors}")

    async def _try_fill_first_available(
        self, page: Page, selectors: list[str], value: str
    ) -> bool:
        for selector in selectors:
            loc = page.locator(selector)
            try:
                if await loc.count():
                    await loc.first.fill(value)
                    return True
            except PlaywrightError:
                continue
        return False

    async def _click_by_text(self, page: Page, labels: list[str]) -> None:
        clicked = await self._try_click_by_text(page, labels, required=True)
        if not clicked:
            raise RuntimeError(f"Could not click any button/link with labels: {labels}")

    async def _try_click_by_text(
        self, page: Page, labels: list[str], required: bool
    ) -> bool:
        for label in labels:
            candidates = [
                page.get_by_role("button", name=label),
                page.get_by_role("link", name=label),
                page.get_by_text(label, exact=True),
            ]
            for candidate in candidates:
                try:
                    if await candidate.count():
                        await candidate.first.click()
                        return True
                except (PlaywrightError, PlaywrightTimeoutError):
                    continue
        if required:
            logger.error("Could not find clickable text among: %s", labels)
        return False

    async def _capture_failure(self, page: Page) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        screenshot = self.settings.log_dir / f"substack-failure-{stamp}.png"
        html = self.settings.log_dir / f"substack-failure-{stamp}.html"
        try:
            await page.screenshot(path=screenshot, full_page=True)
            html.write_text(await page.content(), encoding="utf-8")
            logger.error("Captured failure screenshot: %s", screenshot)
            logger.error("Captured failure HTML: %s", html)
        except PlaywrightError as exc:
            logger.error("Could not capture Playwright failure artifacts: %s", exc)

    @staticmethod
    def _markdown_without_title(markdown: str) -> str:
        lines = markdown.splitlines()
        if lines and lines[0].startswith("# "):
            return "\n".join(lines[1:]).strip()
        return markdown.strip()

