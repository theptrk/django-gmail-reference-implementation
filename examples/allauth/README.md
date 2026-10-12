# Adapting the reference to django-allauth

This optional, runnable example demonstrates allauth's account UI and Google OAuth
boundary. The main reference continues to use Django login and custom Gmail OAuth
views. Choose the boundary that fits your host application; do not run both OAuth
implementations for the same connection.

The example does **not** import mail or attach allauth tokens to `GmailMailbox`.
Those application responsibilities are described below. Its purpose is to make
the UI integration concrete and testable before connecting the sync workers.

## Run it locally

From the repository root:

```bash
uv sync --extra allauth
uv run python manage.py migrate --settings=examples.allauth.settings
uv run python manage.py createsuperuser --settings=examples.allauth.settings
```

Check that port 8001 is free before starting the server. Then:

```bash
uv run python manage.py runserver 127.0.0.1:8001 --settings=examples.allauth.settings
```

Open `http://127.0.0.1:8001/` and sign in using that local user's username and password.
The example uses `allauth-example.sqlite3`, separate from the main `db.sqlite3`.
Redis, Google credentials, and a token encryption key are not needed to inspect
the account UI or run its tests.

Without Google credentials, the dashboard explains what is missing. Account
connections still renders with the host application's styling, but has no Google
button. This means the OAuth client is not configured, not that CSS failed to load.

To authorize a real Google account, set `GOOGLE_CLIENT_ID` and
`GOOGLE_CLIENT_SECRET` in the repository's `.env`, restart the server, enable the
Gmail API, and register this exact Web application redirect URI in Google Cloud:

```text
http://127.0.0.1:8001/accounts/google/login/callback/
```

This differs from the main reference's `/gmail/callback/`. Add your Google account
as a test user while the consent screen is in Testing. The settings example uses
`SOCIALACCOUNT_PROVIDERS["google"]["APP"]`; an existing host application can use a
database `SocialApp` instead. Configure a given client in one place only. If your
host uses Django Sites, also associate a database app with the active site.

## Why the shared layout matters

Django searches configured template directories before installed applications.
An override works only when its name matches the template that the page actually
inherits. Styling the old `account/base.html`, login, and signup templates does
not cover current allauth's built-in social account pages:

```text
socialaccount/connections.html -> socialaccount/base_manage.html
                             -> allauth/layouts/manage.html
                             -> allauth/layouts/base.html

socialaccount/login.html      -> socialaccount/base_entrance.html
and authentication errors     -> allauth/layouts/entrance.html
                             -> allauth/layouts/base.html
```

The example puts its template directory before the main reference's directory,
then supplies this shared bridge at
`templates/allauth/layouts/base.html`:

```django
{% extends "base.html" %}
{% block title %}{% block head_title %}{% endblock %} · Django Gmail Reference{% endblock %}
```

Here `base.html` is the host application's template. It owns CSS, navigation,
messages, and the `content` block. It also exposes `extra_head` and `extra_body`
so allauth's page assets have somewhere to render. If your host uses different
block names, map those blocks in the bridge. Keep the page's `content` block
intact: allauth's children override it, so a wrapper placed only inside the
bridge's `content` block will be replaced.

Built-in entrance and management layouts already extend this shared base;
override them separately only when they need different arrangements. Allauth's
element templates provide another extension point: this example gives provider
links the host's `.button` class in `allauth/elements/provider.html`. A Bootstrap
host can similarly override button/field elements while preserving their slots,
form attributes, labels, errors, and CSRF tokens.

See [allauth's template documentation](https://docs.allauth.org/en/latest/common/templates.html)
for the supported layouts and elements. Use these extension points rather than
copying whole OAuth views just to style their output.

## Sign-in, connection, and offline access are separate

Ordinary Google sign-in requests identity scopes only. The dashboard's **Connect
Gmail** and **Reconnect Gmail** links use:

```django
{% provider_login_url 'google' process='connect' scope=gmail_scope auth_params='prompt=consent' %}
```

`gmail_scope` is `https://www.googleapis.com/auth/gmail.readonly`. Allauth adds it
to the identity scopes for this request. `process='connect'` links Google to the
already authenticated local user; `prompt=consent` asks Google to issue offline
credentials. Offline access and PKCE are configured in provider settings. The
example leaves `SOCIALACCOUNT_LOGIN_ON_GET=False`: a GET shows a styled
confirmation, and its CSRF-protected POST starts OAuth. Do not globally force
consent on every ordinary sign-in.

Allauth owns authorization state, PKCE, callback handling, account linking, and
token persistence when `SOCIALACCOUNT_STORE_TOKENS=True`. A `SocialAccount` means
an identity is linked. A `SocialToken.token_secret` contains the refresh token;
an absent or empty value means offline credentials are unavailable. Neither an
identity nor a refresh token alone proves Gmail access is authorized. Verify
granted scopes and actual Gmail API access before declaring syncing ready.

On a rejected refresh token, apply the recovery described in the main README:
clear the unusable refresh token, retain imported data and the history cursor,
stop scheduled syncs, and show reconnect. This UI example renders that state;
it does not itself contact Google to detect revocation.

**Manage account connections** uses allauth's normal removal form. Removing a
connection is a CSRF-protected POST and deletes the local `SocialAccount` and
its `SocialToken` rows. It does not revoke Google's grant or delete imported mail.
If your product promises those effects, implement them explicitly and make the
confirmation text describe them.

## Connect it to the Gmail backend

When adapting this into a real product:

1. After a successful allauth connection, validate the Gmail permission and
   resolve the mailbox identity through the Gmail API. Use an adapter or the
   appropriate [social account signal](https://docs.allauth.org/en/latest/socialaccount/signals.html),
   including reconnections, rather than modifying the protocol implementation.
2. Preserve existing refresh tokens when Google omits a new one. Allauth does
   this when saving `SocialToken`; retain that behavior in any mailbox bridge.
3. Establish one owner of refresh credentials. The main reference encrypts them
   in `GmailMailbox`; allauth's default `SocialToken` storage is not encrypted.
   Define encryption and coordinate refresh/revocation before retaining another
   copy. Never expose tokens to browser code or logs.
4. Adapt `credentials_for` and reconnect recovery to that credential owner,
   then reuse the bounded import/history-sync workers and cursor handling.
5. Decide what disconnect means for Google's grant, saved mail, and queued
   tasks. Apply those effects consistently across every disconnect entry point.

Email verification is disabled in this local example for convenience. Choose
your host's verification policy and production cookie/HTTPS settings before use.

## Verify the integration

```bash
# Main custom OAuth implementation:
uv run pytest gmail_integration/tests

# Optional allauth UI implementation:
uv run --extra allauth pytest examples/allauth/tests.py --ds=examples.allauth.settings
uv run --extra allauth python manage.py check --settings=examples.allauth.settings
```

The allauth tests use fake credentials and make no Google requests. They cover
missing configuration, styled login/signup/connections/confirmation/error pages,
Gmail-only connect scopes, offline consent, PKCE, reconnect with missing tokens,
and removal of local credentials with CSRF protection. The extra dependency
installs `django-allauth[socialaccount]`, including the Google provider's PyJWT
dependency.

For browser verification, inspect the signed-out login, account connections,
and Google confirmation pages. Follow the connect link only as far as the local
confirmation to check styling. A real consent/callback and a real Gmail sync
still require your configured Google account; automated UI tests do not prove
those external services succeeded.
