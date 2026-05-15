"""Substack publishing automation using Playwright."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import (
    BrowserContext,
    Error as PlaywrightError,
    Locator,
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
        if await self._already_logged_in(page):
            logger.info("Already logged in to Substack")
            return

        logger.info("Opening Substack login")
        await page.goto("https://substack.com/sign-in", wait_until="domcontentloaded")

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
            timeout_ms=10_000,
        )
        if password_filled:
            await self._click_by_text(page, ["Continue", "Sign in", "Log in"])

        await page.wait_for_load_state("domcontentloaded")
        if not await self._already_logged_in(page):
            raise RuntimeError(
                "Substack login did not complete. Check credentials or two-factor/email-code requirements."
            )

    async def _already_logged_in(self, page: Page) -> bool:
        try:
            await page.goto("https://substack.com/home", wait_until="domcontentloaded")
            if "sign-in" in page.url or "login" in page.url:
                return False
            if await page.locator('input[type="email"], input[type="password"]').count():
                return False
            return await self._is_visible_text(page, ["Create"], timeout_ms=5_000)
        except PlaywrightError:
            return False

    async def _is_visible_text(
        self, page: Page, labels: list[str], timeout_ms: int = 3_000
    ) -> bool:
        for label in labels:
            name = re.compile(rf"^\s*{re.escape(label)}\s*$", re.IGNORECASE)
            candidates = [
                page.get_by_role("button", name=name),
                page.get_by_role("link", name=name),
                page.get_by_text(name),
            ]
            for candidate in candidates:
                try:
                    await candidate.first.wait_for(state="visible", timeout=timeout_ms)
                    return True
                except (PlaywrightError, PlaywrightTimeoutError):
                    continue
        return False

    @retry_async(attempts=3, initial_delay=2.0)
    async def _create_post(self, page: Page, markdown: str) -> None:
        logger.info("Opening new article editor")
        await self._open_article_editor(page)

        title = extract_title(markdown)
        body = self._markdown_without_title(markdown)

        await self._fill_title(page, title)
        await self._paste_body(page, body)

    async def _open_article_editor(self, page: Page) -> None:
        await page.goto("https://substack.com/home", wait_until="domcontentloaded")
        await self._click_by_text(page, ["Create"])
        await self._click_by_text(page, ["Article"])
        await self._try_click_by_text(page, ["Continue"], required=False, timeout_ms=8_000)
        await self._wait_for_editor_ready(page)

    async def _wait_for_editor_ready(self, page: Page) -> None:
        candidates = [
            'textarea[placeholder*="Title"]',
            'input[placeholder*="Title"]',
            '[contenteditable="true"][data-placeholder*="Title"]',
            '[contenteditable="true"][aria-label*="Title"]',
            ".ProseMirror",
            '[contenteditable="true"]',
        ]
        try:
            await page.wait_for_function(
                """
                selectors => selectors.some(selector => {
                    const element = document.querySelector(selector);
                    if (!element) return false;
                    const style = window.getComputedStyle(element);
                    const box = element.getBoundingClientRect();
                    return style.visibility !== 'hidden'
                        && style.display !== 'none'
                        && box.width > 0
                        && box.height > 0;
                })
                """,
                candidates,
                timeout=self.settings.playwright_timeout_ms,
            )
        except PlaywrightTimeoutError as exc:
            raise RuntimeError("Substack editor did not become visible") from exc

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
        await self._click_by_text(page, ["Continue", "Publish"])
        await page.wait_for_timeout(1500)
        await self._try_click_by_text(
            page,
            ["Send to everyone now", "Publish now", "Publish", "Send"],
            required=True,
            timeout_ms=self.settings.playwright_timeout_ms,
        )
        await page.wait_for_load_state("domcontentloaded")

    async def _fill_first_available(
        self, page: Page, selectors: list[str], value: str
    ) -> None:
        if not await self._try_fill_first_available(page, selectors, value):
            raise RuntimeError(f"None of these fields were found: {selectors}")

    async def _try_fill_first_available(
        self,
        page: Page,
        selectors: list[str],
        value: str,
        timeout_ms: int = 3_000,
    ) -> bool:
        for selector in selectors:
            loc = page.locator(selector)
            try:
                first = loc.first
                await first.wait_for(state="visible", timeout=timeout_ms)
                await first.fill(value)
                return True
            except (PlaywrightError, PlaywrightTimeoutError):
                continue
        return False

    async def _click_by_text(self, page: Page, labels: list[str]) -> None:
        clicked = await self._try_click_by_text(page, labels, required=True)
        if not clicked:
            raise RuntimeError(f"Could not click any button/link with labels: {labels}")

    async def _try_click_by_text(
        self,
        page: Page,
        labels: list[str],
        required: bool,
        timeout_ms: int | None = None,
    ) -> bool:
        timeout = timeout_ms or (self.settings.playwright_timeout_ms if required else 3_000)
        for label in labels:
            name = re.compile(rf"^\s*{re.escape(label)}\s*$", re.IGNORECASE)
            candidates = [
                page.get_by_role("button", name=name),
                page.get_by_role("link", name=name),
                page.get_by_text(name),
            ]
            for candidate in candidates:
                if await self._try_click_locator(candidate, timeout):
                    return True
        if required:
            logger.error("Could not find clickable text among: %s", labels)
        return False

    async def _try_click_locator(self, locator: Locator, timeout_ms: int) -> bool:
        try:
            first = locator.first
            await first.wait_for(state="visible", timeout=timeout_ms)
            await first.click(timeout=timeout_ms)
            return True
        except (PlaywrightError, PlaywrightTimeoutError):
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
