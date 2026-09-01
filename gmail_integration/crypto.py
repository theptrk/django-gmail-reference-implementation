import base64
import hashlib

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _key():
    configured = settings.GMAIL_TOKEN_ENCRYPTION_KEY
    if configured:
        return configured.encode()
    if not settings.DEBUG:
        raise ImproperlyConfigured("GMAIL_TOKEN_ENCRYPTION_KEY is required when DEBUG=false")
    return base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())


def encrypt(value: str) -> str:
    return Fernet(_key()).encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return Fernet(_key()).decrypt(value.encode()).decode()
