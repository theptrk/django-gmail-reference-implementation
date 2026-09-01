from django.contrib import admin

from .models import GmailMailbox, GmailMessage, GmailSyncRun

admin.site.register(GmailMailbox)
admin.site.register(GmailSyncRun)
admin.site.register(GmailMessage)
