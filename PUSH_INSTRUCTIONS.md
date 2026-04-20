# How to push the updated Weekend QA Bot

## What changed (latest — link fixes)

1. **429/503 rate-limit filtering** — HTTP 429 and 503 responses are no longer flagged as broken links (they're rate-limit responses, not actual broken pages)
2. **Link anchor text in reports** — Broken links now include the visible link text (e.g. `"Buy Now"`, `"Learn More"`) so issues can be located on the page quickly
3. **RATE_LIMIT_CODES constant** — `{429, 503}` set used across image checks, nav link checks, and all link validators
4. **`_extract_link_text()` helper** — Extracts `<a>` tag inner text by href for human-readable broken link reports

## How to push

1. Clone your repo (if you haven't already):
   ```
   git clone https://github.com/8amitjain/weekend-qa-bot.git
   cd weekend-qa-bot
   ```

2. Copy the updated file from this folder into the repo:
   - `api/cron.py` → replace `api/cron.py`

3. Commit and push:
   ```
   git add api/cron.py
   git commit -m "Fix broken link reporting: filter 429/503 rate limits, add anchor text context"
   git push origin main
   ```

## Required GitHub Secrets

Make sure these secrets are set in your repo (Settings → Secrets → Actions):

- `SLACK_BOT_TOKEN` — Your Slack Bot OAuth token (starts with `xoxb-`)
- `SLACK_CHANNEL_ID` — Set to `C0AP3RF4J4B` (#automated-qc)

## Required Slack Bot Scopes

Your Slack app MUST have these OAuth scopes (https://api.slack.com/apps → your app → OAuth & Permissions):

- `chat:write` — Post messages to channels
- `files:write` — Upload PDF reports (**REQUIRED for per-site PDFs**)
- `files:read` — Share uploaded files in channels

**If `files:write` is missing**, the summary message will still post but individual PDF reports will fail. The bot now detects this and falls back to posting text summaries instead.

After adding scopes, you must **reinstall the app** to your workspace for the changes to take effect. Then update the `SLACK_BOT_TOKEN` secret in GitHub if the token changed.

## How it runs

- **Schedule:** Every Saturday at 8am EST (1pm UTC) via GitHub Actions
- **Manual trigger:** Go to Actions tab → "Weekend QA Audit" → "Run workflow"
- **No computer needed** — runs entirely on GitHub's servers

## What it checks (per site)

- Broken images (fetches actual image URLs)
- Broken navigation links (with anchor text for locating)
- SSL certificate health
- Page load performance
- E-commerce: cart, checkout, upsell, pricing, payment badges
- Compliance: FDA disclaimer, terms/privacy, contact info
- Social media link validation
- Mixed content (HTTP on HTTPS)
- Placeholder text detection
- 429/503 rate-limit responses correctly filtered out
