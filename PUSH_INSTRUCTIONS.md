# How to push the updated Weekend QA Bot

## Option 1: Copy files directly (easiest)

1. Clone your repo (if you haven't already):
   ```
   git clone https://github.com/8amitjain/weekend-qa-bot.git
   cd weekend-qa-bot
   ```

2. Copy the updated files from this folder into the repo:
   - `api/cron.py` → replace `api/cron.py`
   - `.github/workflows/weekend-qa.yml` → replace `.github/workflows/weekend-qa.yml`

3. Commit and push:
   ```
   git add api/cron.py .github/workflows/weekend-qa.yml
   git commit -m "Per-site PDF reports with core QA checks, no ecommerce"
   git push origin main
   ```

## Option 2: Apply the patch file

1. Clone and cd into your repo
2. Apply the patch:
   ```
   git am update.patch
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
- Broken navigation links
- SSL certificate health
- Page load performance
- Meta tags (title, description, viewport)
- Missing H1, canonical, favicon
- Mixed content (HTTP on HTTPS)
- Placeholder text detection
- robots.txt and sitemap.xml
- NOT ecommerce (no CTA/cart/checkout checks)
