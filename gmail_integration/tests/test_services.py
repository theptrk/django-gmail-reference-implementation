import base64

import pytest
from django.contrib.auth import get_user_model

from gmail_integration.crypto import decrypt, encrypt
from gmail_integration.models import GmailMailbox, GmailMessage, GmailSyncRun
from gmail_integration.services import save_message


@pytest.fixture
def mailbox(db, settings):
    settings.DEBUG = True
    user = get_user_model().objects.create_user("person", password="password")  # noqa: S106
    return GmailMailbox.objects.create(
        user=user, email="person@example.com", encrypted_refresh_token=encrypt("secret")
    )


def test_refresh_token_round_trip(settings):
    settings.DEBUG = True
    assert decrypt(encrypt("refresh-token")) == "refresh-token"


def test_save_message_is_idempotent(mailbox):
    run = GmailSyncRun.objects.create(mailbox=mailbox, status=GmailSyncRun.Status.RUNNING)
    body = base64.urlsafe_b64encode(b"hello").decode()
    payload = {
        "id": "m1",
        "threadId": "t1",
        "internalDate": "1700000000000",
        "snippet": "hi",
        "labelIds": ["INBOX"],
        "payload": {
            "mimeType": "text/plain",
            "headers": [{"name": "Subject", "value": "Hello"}],
            "body": {"data": body},
        },
    }
    assert save_message(mailbox, payload, run) is True
    assert save_message(mailbox, payload, run) is False
    assert GmailMessage.objects.count() == 1
    run.refresh_from_db()
    assert (run.processed_count, run.created_count, run.updated_count) == (2, 1, 1)
