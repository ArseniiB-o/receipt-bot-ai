# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability, please **do not open a public GitHub issue**.

Instead, report it privately:
1. Open a [GitHub Security Advisory](https://github.com/ArseniiB-o/receipt-bot/security/advisories/new) on this repository, or
2. Email the maintainer directly (see GitHub profile).

Please include:
- A description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested fix (optional)

You will receive a response within 72 hours. We take all reports seriously.

---

## What Data the Bot Stores

| Data | Where | Retention |
|---|---|---|
| Receipt amount, store, date, category, items | SQLite (`receipts.db`) | Until manually deleted |
| Receipt images / PDFs | `receipts/` folder | Until manually deleted |
| Telegram user ID and username | SQLite | Stored with each receipt |
| User language preference | SQLite `user_settings` | Until manually deleted |
| Raw AI responses | SQLite (truncated to 50 000 chars) | Until manually deleted |
| Google Sheets rows | Google Sheets spreadsheet | Until manually deleted |

**The bot does NOT store:**
- Telegram session tokens
- Passwords or payment data
- Any data outside the configured `receipts/` and `receipts.db` paths

---

## Credentials and Secrets

The following files **must never be committed to version control**:

| File | Contains |
|---|---|
| `.env` | Telegram token, OpenRouter key, user IDs |
| `service_account.json` | Google Cloud service account private key |

Both are listed in `.gitignore`. Verify with `git check-ignore -v .env service_account.json`.

---

## Rotating Credentials

### Telegram Bot Token
1. Message [@BotFather](https://t.me/BotFather) → `/mybots` → select your bot → **Revoke current token**
2. Copy the new token into `.env` → `TELEGRAM_BOT_TOKEN=`
3. Restart the bot

### OpenRouter API Key
1. Go to [openrouter.ai/keys](https://openrouter.ai/keys)
2. Delete the old key and create a new one
3. Update `.env` → `OPENROUTER_API_KEY=`
4. Restart the bot

### Google Service Account
1. Go to [Google Cloud Console](https://console.cloud.google.com/) → IAM & Admin → Service Accounts
2. Select the account → Keys → **Add Key** → JSON
3. Delete the old key
4. Replace `service_account.json` with the new file
5. Restart the bot

### Revoking User Access
Remove the user's ID from `ALLOWED_USER_IDS` in `.env` and restart the bot.

---

## Security Features

- **Access control** — all handlers require the user's ID to be in `ALLOWED_USER_IDS`
- **Path traversal guard** — all file paths validated with `safe_file_path()` before use
- **Magic-byte validation** — uploaded image files verified against their declared MIME type
- **Rate limiting** — 10 requests/minute per user; excess requests silently dropped
- **AI semaphore** — max 2 concurrent OpenRouter calls to prevent API storms
- **Sheets write lock** — `asyncio.Lock` prevents concurrent writes to the same spreadsheet
- **Input bounds** — receipt amounts capped at 1 000 000; strings truncated; items list capped at 100
- **Log safety** — httpx INFO logs suppressed to prevent bot token appearing in log files
