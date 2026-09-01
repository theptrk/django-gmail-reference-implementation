from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import GmailMailbox, GmailSyncRun
from .services import sync_mailbox


@shared_task(bind=True, max_retries=3, soft_time_limit=900, time_limit=1200)
def sync_gmail_mailbox(self, mailbox_id, run_id=None):
    run = (
        GmailSyncRun.objects.get(pk=run_id)
        if run_id
        else GmailSyncRun.objects.create(
            mailbox_id=mailbox_id, status=GmailSyncRun.Status.RUNNING, task_id=self.request.id or ""
        )
    )
    try:
        sync_mailbox(mailbox_id, run.pk, resume=bool(run_id))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=min(60 * (2**self.request.retries), 600)) from exc
    mailbox = GmailMailbox.objects.get(pk=mailbox_id)
    if mailbox.status == GmailMailbox.Status.SYNCING and mailbox.full_sync_page_token:
        self.apply_async(args=(mailbox_id,), kwargs={"run_id": run.pk}, countdown=1)


@shared_task
def sync_due_gmail_mailboxes():
    now = timezone.now()
    stale_before = now - timedelta(seconds=settings.GMAIL_SYNC_LEASE_SECONDS)
    ids = list(
        GmailMailbox.objects.filter(
            Q(next_sync_at__lte=now)
            | Q(status=GmailMailbox.Status.SYNCING, sync_started_at__lte=stale_before)
        ).values_list("id", flat=True)
    )
    for mailbox_id in ids:
        with transaction.atomic():
            mailbox = GmailMailbox.objects.select_for_update().get(pk=mailbox_id)
            run = mailbox.sync_runs.filter(status=GmailSyncRun.Status.RUNNING).first()
            mailbox.sync_started_at = now
            mailbox.save(update_fields=["sync_started_at", "updated_at"])
        sync_gmail_mailbox.delay(mailbox_id, run_id=run.pk if run else None)
