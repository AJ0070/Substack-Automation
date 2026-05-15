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


class CloudflareChallengeError(RuntimeError):
    """Raised when Substack returns a Cloudflare verification page."""


class SubstackPublisher:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def publish_markdown(self, markdown: str, source_path: Path) -> None:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=self.settings.headless)
            try:
                context = await self._new_context(browser)
                context.set_default_timeout(self.settings.playwright_timeout_ms)
                await self._grant_clipboard_permissions(context)
                page = await context.new_page()

                try:
                    await self._login(page)
                    await self._save_auth_state(context)
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

    async def login_only(self) -> None:
        if self.settings.substack_auth_state_path is None:
            raise RuntimeError("Set SUBSTACK_AUTH_STATE_PATH before running --login-only")

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=self.settings.headless)
            try:
                context = await self._new_context(browser)
                context.set_default_timeout(self.settings.playwright_timeout_ms)
                await self._grant_clipboard_permissions(context)
                page = await context.new_page()
                try:
                    await self._login(page)
                    await self._save_auth_state(context)
                    logger.info(
                        "Saved Substack auth state to %s",
                        self.settings.substack_auth_state_path,
                    )
                finally:
                    await context.close()
            finally:
                await browser.close()

    async def _new_context(self, browser):
        kwargs = {
            "viewport": {"width": 1440, "height": 1100},
            "ignore_https_errors": False,
        }
        auth_state_path = self.settings.substack_auth_state_path
        if auth_state_path and auth_state_path.exists():
            logger.info("Loading Substack auth state from %s", auth_state_path)
            kwargs["storage_state"] = str(auth_state_path)
        return await browser.new_context(**kwargs)

    async def _save_auth_state(self, context: BrowserContext) -> None:
        auth_state_path = self.settings.substack_auth_state_path
        if auth_state_path is None:
            return
        auth_state_path.parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=auth_state_path)

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

    async def _login(self, page: Page) -> None:
        if await self._already_logged_in(page):
            logger.info("Already logged in to Substack")
            return

        logger.info("Opening Substack login")
        await page.goto("https://substack.com/sign-in", wait_until="domcontentloaded")
        await page.wait_for_timeout(2_000)
        await self._raise_if_cloudflare_challenge(page)

        await self._try_click_by_text(
            page,
            [
                "Sign in with email",
                "Continue with email",
                "Use email",
                "Email",
                "Log in with email",
            ],
            required=False,
            timeout_ms=5_000,
        )

        await self._fill_first_available(
            page,
            [
                'input[type="email"]',
                'input[name="email"]',
                'input[name="email_address"]',
                'input[name="emailAddress"]',
                'input[name="emailOrUsername"]',
                'input[autocomplete="email"]',
                'input[placeholder*="email" i]',
                'input[aria-label*="email" i]',
                'input[type="text"]',
            ],
            self.settings.substack_email,
            timeout_ms=10_000,
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
        await self._raise_if_cloudflare_challenge(page)
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
        self,
        page: Page,
        selectors: list[str],
        value: str,
        timeout_ms: int = 3_000,
    ) -> None:
        if await self._try_fill_first_available(page, selectors, value, timeout_ms):
            return
        if await self._try_fill_textbox_by_name(page, value, timeout_ms):
            return
        if await self._try_fill_any_visible_input(page, value, timeout_ms):
            return

        await self._log_page_state(page, "Could not find fillable field")
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

    async def _try_fill_textbox_by_name(
        self, page: Page, value: str, timeout_ms: int
    ) -> bool:
        for name in [
            re.compile(r"email", re.IGNORECASE),
            re.compile(r"email address", re.IGNORECASE),
        ]:
            try:
                textbox = page.get_by_role("textbox", name=name).first
                await textbox.wait_for(state="visible", timeout=timeout_ms)
                await textbox.fill(value)
                return True
            except (PlaywrightError, PlaywrightTimeoutError):
                continue
        return False

    async def _try_fill_any_visible_input(
        self, page: Page, value: str, timeout_ms: int
    ) -> bool:
        inputs = page.locator(
            'input:not([type="hidden"]):not([type="submit"]):not([type="button"])'
        )
        try:
            count = await inputs.count()
        except PlaywrightError:
            return False

        for index in range(count):
            candidate = inputs.nth(index)
            try:
                await candidate.wait_for(state="visible", timeout=timeout_ms)
                await candidate.fill(value)
                return True
            except (PlaywrightError, PlaywrightTimeoutError):
                continue
        return False

    async def _log_page_state(self, page: Page, message: str) -> None:
        try:
            body_text = await page.locator("body").inner_text(timeout=2_000)
        except PlaywrightError:
            body_text = ""
        preview = " ".join(body_text.split())[:500]
        logger.error("%s. url=%s title=%r body_preview=%r", message, page.url, await page.title(), preview)

    async def _raise_if_cloudflare_challenge(self, page: Page) -> None:
        title = await page.title()
        try:
            body_text = await page.locator("body").inner_text(timeout=2_000)
        except PlaywrightError:
            body_text = ""
        normalized = " ".join(body_text.split()).lower()
        if "just a moment" in title.lower() or (
            "cloudflare" in normalized and "security verification" in normalized
        ):
            raise CloudflareChallengeError(
                "Substack is showing Cloudflare security verification. "
                "GitHub-hosted runners are blocked before login; use a self-hosted runner "
                "or run locally with saved Playwright auth state."
            )

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
