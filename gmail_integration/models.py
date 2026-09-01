from django.conf import settings
from django.db import models


class GmailMailbox(models.Model):
    class Status(models.TextChoices):
        CONNECTED = "connected", "Connected"
        SYNCING = "syncing", "Syncing"
        ERROR = "error", "Error"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="gmail_mailbox"
    )
    email = models.EmailField()
    encrypted_refresh_token = models.TextField()
    scopes = models.JSONField(default=list)
    history_id = models.CharField(max_length=64, blank=True)
    full_sync_page_token = models.CharField(max_length=512, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.CONNECTED)
    sync_error = models.TextField(blank=True)
    imported_since = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    next_sync_at = models.DateTimeField(null=True, blank=True)
    sync_started_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.email


class GmailSyncRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    mailbox = models.ForeignKey(GmailMailbox, on_delete=models.CASCADE, related_name="sync_runs")
    status = models.CharField(max_length=16, choices=Status.choices)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    discovered_count = models.PositiveIntegerField(default=0)
    processed_count = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    deleted_count = models.PositiveIntegerField(default=0)
    task_id = models.CharField(max_length=255, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.mailbox.email} sync {self.pk}"


class GmailMessage(models.Model):
    mailbox = models.ForeignKey(GmailMailbox, on_delete=models.CASCADE, related_name="messages")
    gmail_id = models.CharField(max_length=128)
    thread_id = models.CharField(max_length=128, blank=True)
    internal_date = models.DateTimeField(null=True, blank=True)
    sender = models.TextField(blank=True)
    recipients = models.TextField(blank=True)
    subject = models.TextField(blank=True)
    snippet = models.TextField(blank=True)
    body_text = models.TextField(blank=True)
    body_html = models.TextField(blank=True)
    labels = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["mailbox", "gmail_id"], name="unique_gmail_message")
        ]
        indexes = [
            models.Index(fields=["mailbox", "internal_date"], name="gmail_msg_mail_date_idx"),
            models.Index(fields=["mailbox", "thread_id"], name="gmail_msg_mail_thread_idx"),
        ]

    def __str__(self):
        return self.subject or self.gmail_id
