# Substack Automation

A local and GitHub Actions friendly automation system for generating beginner-friendly technical Substack posts with Google AI Studio Gemini and uploading them with Playwright.

## Architecture

- `main.py` orchestrates generation, markdown storage, and publishing.
- `app/generator.py` runs the Gemini pipeline: topic, outline, sections, merge, final polish.
- `app/publisher.py` logs in to Substack with Playwright, creates a post, inserts markdown, and either saves a draft or publishes.
- `app/config.py` loads and validates environment variables.
- `app/prompts.py` keeps prompts isolated and easy to tune.
- `app/utils.py` handles logging, retries, slugs, and markdown persistence.
- `articles/` stores generated markdown files.
- `logs/` stores runtime logs and Playwright failure screenshots/HTML.

## Setup

Use Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
```

Edit `.env` with your credentials.

## Environment Variables

Required:

- `GEMINI_API_KEY`: Google AI Studio API key.
- `SUBSTACK_EMAIL`: Substack login email.
- `SUBSTACK_PASSWORD`: Substack password.
- `PUBLISH_MODE`: `draft` or `publish`.

Recommended:

- `SUBSTACK_PUBLICATION_URL`: your publication URL, for example `https://yourname.substack.com`.
- `HEADLESS`: `true` for CI, `false` for local debugging.
- `ARTICLE_DIR`: defaults to `articles`.
- `LOG_DIR`: defaults to `logs`.
- `MAX_RETRIES`: defaults to `3`.
- `PLAYWRIGHT_TIMEOUT_MS`: defaults to `45000`.

## Gemini API Setup

1. Open Google AI Studio.
2. Create an API key.
3. Add it to `.env` as `GEMINI_API_KEY`.
4. The generator uses `gemini-2.5-flash`.

Run generation only:

```bash
python main.py --skip-publish
```

## Substack Setup

Set:

```env
SUBSTACK_EMAIL=you@example.com
SUBSTACK_PASSWORD=your_password
SUBSTACK_PUBLICATION_URL=https://yourname.substack.com
PUBLISH_MODE=draft
```

Start with draft mode:

```bash
python main.py
```

For local debugging, use:

```env
HEADLESS=false
```

Substack may require email-code or two-factor verification. If that happens, run once locally with `HEADLESS=false`, complete the login manually, or adjust the account security settings for automation. The script logs clear failures and saves screenshots under `logs/`.

Upload an existing markdown file:

```bash
python main.py --markdown-file articles/example.md
```

## GitHub Actions Setup

Create repository secrets:

- `GEMINI_API_KEY`
- `SUBSTACK_EMAIL`
- `SUBSTACK_PASSWORD`
- `SUBSTACK_PUBLICATION_URL`

Create a repository variable:

- `PUBLISH_MODE`: use `draft` first, then `publish` when verified.

The workflow lives at `.github/workflows/publish.yml` and runs:

- manually through `workflow_dispatch`
- every Monday at 08:00 UTC by cron

Generated articles and logs are uploaded as workflow artifacts.

## Playwright Strategy

The publisher uses:

- headless Chromium by default
- accessible roles and text selectors first
- CSS selector fallbacks for editor fields
- explicit load-state waits and short stabilization waits
- retries around login, editor creation, save, and publish
- failure screenshots and HTML captures in `logs/`

Substack is a private web UI, so selectors can change. If publishing fails, inspect the saved screenshot and HTML, then update the selector candidates in `app/publisher.py`.

## Troubleshooting

`Missing required environment variable`

Check `.env` locally or GitHub secrets in CI.

`Substack login did not complete`

Credentials may be wrong, or Substack may require email-code/two-factor verification. Run with `HEADLESS=false` to inspect the login flow.

`Could not find Substack body editor`

Substack changed the editor UI or the publication URL is wrong. Confirm `SUBSTACK_PUBLICATION_URL`, then inspect the failure screenshot and HTML in `logs/`.

`Gemini returned an empty response`

Retry later or lower the generation complexity in `app/prompts.py`.

`playwright install` errors in CI

Use the workflow as provided; it runs `playwright install --with-deps chromium`.

## Production Notes

- Keep `PUBLISH_MODE=draft` until the full flow is verified.
- Do not commit `.env`.
- Use GitHub secrets for credentials.
- Prefer one scheduled run at a time to avoid duplicate posts.
- Keep generated markdown in `articles/` for review and auditability.

