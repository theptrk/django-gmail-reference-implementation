# Django Gmail reference implementation

A small, production-minded Django project showing how to connect a user's Gmail account, securely retain offline credentials, import recent mail, and keep it synchronized with Gmail history records.

This is deliberately a reference, not a reusable package. Copy the architecture and adapt the product decisions to your application.

## What it demonstrates

- OAuth 2.0 authorization-code flow with PKCE, state validation, offline access, and refresh-token preservation
- encrypted refresh tokens (never sent to the browser)
- an idempotent message model with a `(mailbox, gmail_id)` uniqueness constraint
- resumable, page-at-a-time initial imports through Celery
- incremental synchronization through `users.history.list`
- expired history cursor recovery (HTTP 404 triggers a new full import)
- revoked-access recovery: a rejected refresh token stops syncing and asks the user to reconnect
- task leases, stale-worker recovery, durable sync-run counters, and status polling
- deletion of local connection data

The example requests only `gmail.readonly`. It imports the last 90 days and excludes Spam and Trash by default.

## Architecture

```text
Browser -> Django OAuth views -> Google OAuth/Gmail API
             |                       |
             v                       v
          database <----------- Celery worker
             ^                       ^
             |                       |
        status polling          Celery beat
```

Django owns users, sessions, encrypted credentials, normalized messages, cursors, leases, and sync status. Google's maintained libraries own OAuth and API protocol. Celery workers perform bounded background work; the browser polls Django, never Google.

## Quick start

Prerequisites: Python 3.12+, [uv](https://docs.astral.sh/uv/), Docker (or another Redis installation), and a Google Cloud project.

```bash
cp .env.example .env
uv sync
uv run python manage.py migrate
uv run python manage.py createsuperuser
docker compose up -d redis
uv run celery -A config worker -l info
```

In another terminal:

```bash
uv run celery -A config beat -l info
```

And in a third:

```bash
uv run python manage.py runserver
```

Open `http://127.0.0.1:8000`, log in, and connect Gmail.

For UI-only development without Redis, set `CELERY_TASK_ALWAYS_EAGER=true`; note that an initial import then runs inside the web request and is unsuitable for real workloads.

## Google Cloud configuration

1. Create or select a Google Cloud project and enable the Gmail API.
2. Configure the OAuth consent screen. While the app is in Testing, add each developer Gmail account as a test user.
3. Create an OAuth client with application type **Web application**.
4. Add this exact authorized redirect URI:

   `http://127.0.0.1:8000/gmail/callback/`

5. Put the client ID and client secret in `.env`.
6. Generate an independent Fernet key and put it in `.env`:

```bash
uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Production HTTPS, proxy headers, hosts, cookies, database, Redis, secret management, and redirect URI must be configured for your deployment. Never rotate the Fernet key without re-encrypting stored tokens.

## Important implementation choices

`GmailMailbox.user` is one-to-one because this demo permits one Gmail account per user. A multi-account product should use a foreign key and a provider-account uniqueness constraint.

The full import saves `nextPageToken` before scheduling its continuation. Each message is upserted, so replaying a page is safe. Incremental sync stores Gmail's newest `historyId`; additions and label changes are refetched, while deletions remove the local row. Gmail can expire history IDs, so a 404 resets the cursor and starts a full import.

### Recovering from revoked or missing refresh tokens

Google only issues a refresh token when the consent screen is shown, and it can invalidate one at any time (the user removes access, changes their password, or the app is in Testing and the token is older than 7 days). None of this can be repaired server side; the user has to consent again. The reference therefore:

1. Always sends `prompt=consent` on connect, so a refresh token is issued.
2. Keeps the stored refresh token when Google does not return a new one.
3. Treats `invalid_grant`, HTTP 401, and insufficient-scope 403s as `ReconnectRequired`. Rate limits, 5xx responses, and retryable refresh failures still raise and retry.
4. On `ReconnectRequired`, discards the dead token, sets the mailbox to `needs_reconnect`, clears `next_sync_at` so Celery beat stops retrying, and keeps `history_id` so reconnecting resumes incremental sync.
5. Shows a **Reconnect Gmail** button and refuses manual syncs until the user reconnects.

#### Using django-allauth instead

If Google sign-in already goes through django-allauth, you don't need the custom OAuth views; apply the same recovery to `SocialToken`:

| This reference | django-allauth |
| --- | --- |
| `prompt="consent"` in `views.connect` | `{% provider_login_url "google" process="connect" auth_params="prompt=consent" %}` on connect/reconnect links only; keep `AUTH_PARAMS = {"access_type": "offline"}` in settings |
| Preserve the refresh token in `views.callback` | Built in: allauth only overwrites `SocialToken.token_secret` when Google sends a new refresh token |
| `GmailMailbox.encrypted_refresh_token` | `SocialToken.token_secret` (plain text; encrypt if required) |
| `Status.NEEDS_RECONNECT` | An empty `SocialToken.token_secret` |
| `credentials_for` + refresh | Build `Credentials` from the token (including `expiry=token.expires_at` as naive UTC) and refresh only when `credentials.valid` is false; save the new access token and `expires_at` |
| `mark_needs_reconnect` | `token.token_secret = ""`, then render a Reconnect link instead of an empty page |

Install allauth with the `socialaccount` extra (`django-allauth[socialaccount]`). Since allauth 65, PyJWT is optional, and without it the Google callback fails with `ModuleNotFoundError: No module named 'jwt'` after the user consents.

The body parser intentionally stores inline text/plain and text/html parts but skips attachments. Treat HTML as untrusted if you render it. Real products should also define retention, redaction, attachment, search, revocation, and account-deletion policies.

## Test and inspect

```bash
uv run pytest
uv run ruff check .
uv run python manage.py check
uv run python manage.py makemigrations --check
```

Start with these files when adapting the reference:

- `gmail_integration/views.py` — OAuth boundary and authenticated endpoints
- `gmail_integration/services.py` — normalization, full import, and history sync
- `gmail_integration/tasks.py` — retries, continuation, polling, and stale recovery
- `gmail_integration/models.py` — encrypted credential, cursor, run, and message state
- `config/settings.py` — environment and Celery schedule

## Security checklist

- Keep OAuth state and PKCE verifier in the authenticated server-side session and consume them once.
- Encrypt refresh tokens with a dedicated key from a secret manager.
- Request the smallest scope possible and verify authorization on every endpoint.
- Do not log tokens, authorization codes, raw messages, or provider payloads.
- Use HTTPS and secure session/CSRF cookies in production.
- Add a Google token-revocation call to disconnect if your product promises revocation; this demo deletes local data only.
- Review Google's OAuth verification and data-use requirements before publishing.

## License

MIT

