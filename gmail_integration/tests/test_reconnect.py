from datetime import timedelta
from unittest.mock import Mock, patch

import httplib2
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError

from gmail_integration.crypto import encrypt
from gmail_integration.models import GmailMailbox, GmailSyncRun
from gmail_integration.services import is_reconnect_error, sync_mailbox


@pytest.fixture
def mailbox(db, settings):
    settings.DEBUG = True
    user = get_user_model().objects.create_user("person", password="password")  # noqa: S106
    return GmailMailbox.objects.create(
        user=user,
        email="person@example.com",
        encrypted_refresh_token=encrypt("secret"),
        history_id="42",
        next_sync_at=timezone.now() - timedelta(minutes=1),
    )


def _run(mailbox):
    return GmailSyncRun.objects.create(mailbox=mailbox, status=GmailSyncRun.Status.RUNNING)


def _http_error(status, reason, detail_reason=None):
    resp = httplib2.Response({"status": status})
    resp.reason = reason
    details = f', "errors": [{{"reason": "{detail_reason}"}}]' if detail_reason else ""
    body = f'{{"error": {{"code": {status}, "message": "{reason}"{details}}}}}'
    return HttpError(resp, body.encode())


def test_revoked_refresh_token_stops_syncing_and_asks_to_reconnect(mailbox):
    run = _run(mailbox)
    refresh = Mock(side_effect=RefreshError("invalid_grant: Token has been expired or revoked."))
    with patch("gmail_integration.services.Credentials.refresh", refresh):
        assert sync_mailbox(mailbox.pk, run.pk) is False

    mailbox.refresh_from_db()
    run.refresh_from_db()
    assert mailbox.status == GmailMailbox.Status.NEEDS_RECONNECT
    assert mailbox.encrypted_refresh_token == ""
    assert mailbox.next_sync_at is None  # the beat schedule no longer picks it up
    assert mailbox.history_id == "42"  # reconnecting resumes incremental sync
    assert run.status == GmailSyncRun.Status.FAILED


def test_mailbox_without_refresh_token_needs_reconnect(mailbox):
    GmailMailbox.objects.filter(pk=mailbox.pk).update(encrypted_refresh_token="")
    run = _run(mailbox)
    assert sync_mailbox(mailbox.pk, run.pk) is False
    mailbox.refresh_from_db()
    assert mailbox.status == GmailMailbox.Status.NEEDS_RECONNECT


def test_transient_errors_still_raise_for_retry(mailbox):
    run = _run(mailbox)
    rate_limited = _http_error(403, "Rate Limit Exceeded", "rateLimitExceeded")
    with (
        patch("gmail_integration.services.gmail_service"),
        patch("gmail_integration.services._incremental_sync", side_effect=rate_limited),
        pytest.raises(HttpError),
    ):
        sync_mailbox(mailbox.pk, run.pk)
    mailbox.refresh_from_db()
    assert mailbox.status == GmailMailbox.Status.ERROR
    assert mailbox.next_sync_at is not None


def test_reconnect_errors_are_distinguished_from_transient_ones():
    assert is_reconnect_error(RefreshError("invalid_grant"))
    assert not is_reconnect_error(RefreshError("temporarily unavailable", retryable=True))
    assert is_reconnect_error(_http_error(401, "Invalid Credentials"))
    assert is_reconnect_error(
        _http_error(403, "Insufficient Permission", "insufficientPermissions")
    )
    assert not is_reconnect_error(_http_error(403, "Rate Limit Exceeded", "rateLimitExceeded"))
    assert not is_reconnect_error(_http_error(500, "Backend Error"))


def test_dashboard_offers_reconnect_and_sync_is_refused(client, mailbox, monkeypatch):
    GmailMailbox.objects.filter(pk=mailbox.pk).update(
        status=GmailMailbox.Status.NEEDS_RECONNECT, encrypted_refresh_token=""
    )
    delay = Mock()
    monkeypatch.setattr("gmail_integration.views.sync_gmail_mailbox.delay", delay)
    client.force_login(mailbox.user)

    response = client.get(reverse("gmail:dashboard"))
    assert b"Reconnect Gmail" in response.content

    client.post(reverse("gmail:sync"))
    delay.assert_not_called()
