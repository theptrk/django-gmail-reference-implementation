"""An optional UI example; the main reference keeps its custom Gmail OAuth flow."""

from config.settings import *  # noqa: F403
from config.settings import BASE_DIR, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET

INSTALLED_APPS += [  # noqa: F405
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
]
MIDDLEWARE += ["allauth.account.middleware.AccountMiddleware"]  # noqa: F405
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
ROOT_URLCONF = "examples.allauth.urls"
TEMPLATES[0]["DIRS"].insert(0, BASE_DIR / "examples" / "allauth" / "templates")  # noqa: F405
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "allauth-example.sqlite3",
    }
}
LOGIN_URL = "account_login"
LOGIN_REDIRECT_URL = "/"
ACCOUNT_EMAIL_VERIFICATION = "none"  # Local demo; choose a verification policy in production.
ACCOUNT_LOGOUT_REDIRECT_URL = "/accounts/login/"
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
SOCIALACCOUNT_STORE_TOKENS = True
SOCIALACCOUNT_LOGIN_ON_GET = False  # Confirmation renders first; only POST starts OAuth.
SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": ["openid", "profile", "email"],
        "AUTH_PARAMS": {"access_type": "offline"},
        "OAUTH_PKCE_ENABLED": True,
    }
}
if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    # Use settings OR a database SocialApp for this client, not both.
    SOCIALACCOUNT_PROVIDERS["google"]["APP"] = {
        "client_id": GOOGLE_CLIENT_ID,
        "secret": GOOGLE_CLIENT_SECRET,
        "key": "",
    }
