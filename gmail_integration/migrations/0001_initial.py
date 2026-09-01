import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name="GmailMailbox",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("email", models.EmailField(max_length=254)),
                ("encrypted_refresh_token", models.TextField()),
                ("scopes", models.JSONField(default=list)),
                ("history_id", models.CharField(blank=True, max_length=64)),
                ("full_sync_page_token", models.CharField(blank=True, max_length=512)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("connected", "Connected"),
                            ("syncing", "Syncing"),
                            ("error", "Error"),
                        ],
                        default="connected",
                        max_length=16,
                    ),
                ),
                ("sync_error", models.TextField(blank=True)),
                ("imported_since", models.DateTimeField(blank=True, null=True)),
                ("last_synced_at", models.DateTimeField(blank=True, null=True)),
                ("next_sync_at", models.DateTimeField(blank=True, null=True)),
                ("sync_started_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="gmail_mailbox",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="GmailSyncRun",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("running", "Running"),
                            ("succeeded", "Succeeded"),
                            ("failed", "Failed"),
                        ],
                        max_length=16,
                    ),
                ),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("discovered_count", models.PositiveIntegerField(default=0)),
                ("processed_count", models.PositiveIntegerField(default=0)),
                ("created_count", models.PositiveIntegerField(default=0)),
                ("updated_count", models.PositiveIntegerField(default=0)),
                ("deleted_count", models.PositiveIntegerField(default=0)),
                ("task_id", models.CharField(blank=True, max_length=255)),
                ("error", models.TextField(blank=True)),
                (
                    "mailbox",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="sync_runs",
                        to="gmail_integration.gmailmailbox",
                    ),
                ),
            ],
            options={"ordering": ["-started_at"]},
        ),
        migrations.CreateModel(
            name="GmailMessage",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("gmail_id", models.CharField(max_length=128)),
                ("thread_id", models.CharField(blank=True, max_length=128)),
                ("internal_date", models.DateTimeField(blank=True, null=True)),
                ("sender", models.TextField(blank=True)),
                ("recipients", models.TextField(blank=True)),
                ("subject", models.TextField(blank=True)),
                ("snippet", models.TextField(blank=True)),
                ("body_text", models.TextField(blank=True)),
                ("body_html", models.TextField(blank=True)),
                ("labels", models.JSONField(default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "mailbox",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="messages",
                        to="gmail_integration.gmailmailbox",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["mailbox", "internal_date"], name="gmail_msg_mail_date_idx"
                    ),
                    models.Index(fields=["mailbox", "thread_id"], name="gmail_msg_mail_thread_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("mailbox", "gmail_id"), name="unique_gmail_message"
                    )
                ],
            },
        ),
    ]
