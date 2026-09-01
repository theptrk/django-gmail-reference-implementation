import base64
from datetime import UTC, timedelta

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .crypto import decrypt
from .models import GmailMailbox, GmailMessage, GmailSyncRun

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


def credentials_for(mailbox):
    return Credentials(
        token=None,
        refresh_token=decrypt(mailbox.encrypted_refresh_token),
        token_uri="https://oauth2.googleapis.com/token",  # noqa: S106
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=mailbox.scopes or [GMAIL_SCOPE],
    )


def gmail_service(mailbox):
    credentials = credentials_for(mailbox)
    credentials.refresh(Request())
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def _decode(data):
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _header(payload, name):
    return next(
        (
            h.get("value", "")
            for h in payload.get("headers", [])
            if h.get("name", "").lower() == name
        ),
        "",
    )


def _body(payload):
    plain, html = "", ""
    parts = payload.get("parts", []) or [payload]
    for part in parts:
        if part.get("filename"):
            continue
        data = part.get("body", {}).get("data")
        if data:
            text = _decode(data).decode("utf-8", errors="replace")
            if part.get("mimeType") == "text/plain":
                plain += text
            elif part.get("mimeType") == "text/html":
                html += text
        if part.get("parts"):
            child_plain, child_html = _body(part)
            plain += child_plain
            html += child_html
    return plain, html


def save_message(mailbox, message, run=None):
    payload = message.get("payload", {})
    plain, html = _body(payload)
    timestamp = message.get("internalDate")
    _, created = GmailMessage.objects.update_or_create(
        mailbox=mailbox,
        gmail_id=message["id"],
        defaults={
            "thread_id": message.get("threadId", ""),
            "internal_date": timezone.datetime.fromtimestamp(int(timestamp) / 1000, tz=UTC)
            if timestamp
            else None,
            "sender": _header(payload, "from"),
            "recipients": _header(payload, "to"),
            "subject": _header(payload, "subject"),
            "snippet": message.get("snippet", ""),
            "body_text": plain,
            "body_html": html,
            "labels": message.get("labelIds", []),
        },
    )
    if run:
        field = "created_count" if created else "updated_count"
        GmailSyncRun.objects.filter(pk=run.pk).update(
            processed_count=models.F("processed_count") + 1, **{field: models.F(field) + 1}
        )
    return created


def _fetch(service, mailbox, message_id, run=None):
    message = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    return save_message(mailbox, message, run)


def _full_sync(service, mailbox, run):
    since = timezone.now() - timedelta(days=settings.GMAIL_INITIAL_IMPORT_DAYS)
    result = (
        service.users()
        .messages()
        .list(
            userId="me",
            q=f"after:{since:%Y/%m/%d} -label:SPAM -label:TRASH",
            pageToken=mailbox.full_sync_page_token or None,
            maxResults=100,
        )
        .execute()
    )
    items = result.get("messages", [])
    GmailSyncRun.objects.filter(pk=run.pk).update(
        discovered_count=models.F("discovered_count") + len(items)
    )
    for item in items:
        _fetch(service, mailbox, item["id"], run)
    next_token = result.get("nextPageToken", "")
    if next_token:
        GmailMailbox.objects.filter(pk=mailbox.pk).update(full_sync_page_token=next_token)
        return ""
    return service.users().getProfile(userId="me").execute().get("historyId", "")


def _incremental_sync(service, mailbox, run):
    page_token = None
    latest = mailbox.history_id
    while True:
        result = (
            service.users()
            .history()
            .list(userId="me", startHistoryId=mailbox.history_id, pageToken=page_token)
            .execute()
        )
        latest = result.get("historyId", latest)
        for record in result.get("history", []):
            for item in record.get("messagesAdded", []):
                _fetch(service, mailbox, item["message"]["id"], run)
            for item in record.get("messagesDeleted", []):
                deleted, _ = GmailMessage.objects.filter(
                    mailbox=mailbox, gmail_id=item["message"]["id"]
                ).delete()
                if deleted:
                    GmailSyncRun.objects.filter(pk=run.pk).update(
                        deleted_count=models.F("deleted_count") + 1
                    )
            for key in ("labelsAdded", "labelsRemoved"):
                for item in record.get(key, []):
                    _fetch(service, mailbox, item["message"]["id"], run)
        page_token = result.get("nextPageToken")
        if not page_token:
            return latest


def sync_mailbox(mailbox_id, run_id, *, resume=False):
    run = GmailSyncRun.objects.get(pk=run_id)
    with transaction.atomic():
        mailbox = GmailMailbox.objects.select_for_update().get(pk=mailbox_id)
        now = timezone.now()
        lease_valid = (
            mailbox.sync_started_at
            and mailbox.sync_started_at + timedelta(seconds=settings.GMAIL_SYNC_LEASE_SECONDS) > now
        )
        if mailbox.status == GmailMailbox.Status.SYNCING and not resume and lease_valid:
            return False
        mailbox.status = GmailMailbox.Status.SYNCING
        mailbox.sync_started_at = now
        mailbox.sync_error = ""
        mailbox.save(update_fields=["status", "sync_started_at", "sync_error", "updated_at"])
    try:
        service = gmail_service(mailbox)
        try:
            history_id = (
                _incremental_sync(service, mailbox, run)
                if mailbox.history_id
                else _full_sync(service, mailbox, run)
            )
        except HttpError as exc:
            if mailbox.history_id and exc.resp.status == 404:
                GmailMailbox.objects.filter(pk=mailbox.pk).update(
                    history_id="", full_sync_page_token=""
                )
                mailbox.history_id = ""
                mailbox.full_sync_page_token = ""
                history_id = _full_sync(service, mailbox, run)
            else:
                raise
        now = timezone.now()
        if not history_id:
            GmailMailbox.objects.filter(pk=mailbox_id).update(
                next_sync_at=now + timedelta(seconds=1), updated_at=now
            )
            return True
        GmailMailbox.objects.filter(pk=mailbox_id).update(
            history_id=history_id,
            full_sync_page_token="",
            status=GmailMailbox.Status.CONNECTED,
            imported_since=mailbox.imported_since
            or now - timedelta(days=settings.GMAIL_INITIAL_IMPORT_DAYS),
            last_synced_at=now,
            next_sync_at=now + timedelta(minutes=15),
            sync_started_at=None,
            updated_at=now,
        )
        GmailSyncRun.objects.filter(pk=run.pk).update(
            status=GmailSyncRun.Status.SUCCEEDED, finished_at=now
        )
        return True
    except Exception as exc:
        now = timezone.now()
        GmailMailbox.objects.filter(pk=mailbox_id).update(
            status=GmailMailbox.Status.ERROR,
            sync_error=str(exc)[:2000],
            sync_started_at=None,
            next_sync_at=now + timedelta(minutes=15),
            updated_at=now,
        )
        GmailSyncRun.objects.filter(pk=run.pk).update(
            status=GmailSyncRun.Status.FAILED, error=str(exc)[:2000], finished_at=now
        )
        raise
