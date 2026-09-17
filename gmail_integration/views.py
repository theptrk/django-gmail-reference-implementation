from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from .crypto import encrypt
from .models import GmailMailbox
from .services import GMAIL_SCOPE
from .tasks import sync_gmail_mailbox


def _flow(request):
    redirect_uri = request.build_absolute_uri(reverse("gmail:callback"))
    return Flow.from_client_config(
        {
            "web": {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        },
        scopes=[GMAIL_SCOPE],
        redirect_uri=redirect_uri,
    )


@login_required
def dashboard(request):
    mailbox = GmailMailbox.objects.filter(user=request.user).first()
    return render(
        request,
        "gmail_integration/dashboard.html",
        {
            "mailbox": mailbox,
            "sync_run": mailbox.sync_runs.first() if mailbox else None,
            "recent_messages": mailbox.messages.order_by("-internal_date")[:25] if mailbox else [],
        },
    )


@login_required
def connect(request):
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        messages.error(request, "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET first.")
        return redirect("gmail:dashboard")
    flow = _flow(request)
    # Google only issues a refresh token when the consent screen is shown, so
    # connect and reconnect always force it.
    # With django-allauth: SOCIALACCOUNT_PROVIDERS["google"]["AUTH_PARAMS"] =
    # {"access_type": "offline"}, and add prompt=consent on the connect link only
    # (not plain "Sign in with Google", or every login shows the consent screen):
    #   {% provider_login_url "google" process="connect" auth_params="prompt=consent" %}
    authorization_url, state = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent"
    )
    request.session["gmail_oauth_state"] = state
    request.session["gmail_oauth_code_verifier"] = flow.code_verifier
    return redirect(authorization_url)


@login_required
def callback(request):
    expected_state = request.session.pop("gmail_oauth_state", None)
    verifier = request.session.pop("gmail_oauth_code_verifier", None)
    if (
        request.GET.get("error")
        or not expected_state
        or expected_state != request.GET.get("state")
        or not verifier
    ):
        messages.error(request, "Google authorization expired or could not be verified. Try again.")
        return redirect("gmail:dashboard")
    code = request.GET.get("code")
    if not code:
        messages.error(request, "Google did not return an authorization code.")
        return redirect("gmail:dashboard")
    flow = _flow(request)
    flow.code_verifier = verifier
    flow.fetch_token(code=code)
    credentials = flow.credentials
    profile = (
        build("gmail", "v1", credentials=credentials, cache_discovery=False)
        .users()
        .getProfile(userId="me")
        .execute()
    )
    existing_token = (
        GmailMailbox.objects.filter(user=request.user)
        .values_list("encrypted_refresh_token", flat=True)
        .first()
    )
    # Google omits the refresh token when consent was skipped; keep the one we
    # have rather than overwriting it with nothing.
    # With django-allauth this is built in: SocialLogin._store_token only replaces
    # SocialToken.token_secret (the refresh token) when a new one arrives.
    if credentials.refresh_token:
        encrypted_token = encrypt(credentials.refresh_token)
    elif existing_token:
        encrypted_token = existing_token
    else:
        messages.error(
            request, "Google did not return a refresh token. Revoke access and connect again."
        )
        return redirect("gmail:dashboard")
    mailbox, _ = GmailMailbox.objects.update_or_create(
        user=request.user,
        defaults={
            "email": profile["emailAddress"],
            "encrypted_refresh_token": encrypted_token,
            "scopes": list(credentials.scopes or [GMAIL_SCOPE]),
            "status": GmailMailbox.Status.CONNECTED,
            "sync_error": "",
            "sync_started_at": None,
        },
    )
    sync_gmail_mailbox.delay(mailbox.pk)
    messages.success(request, f"Connected {mailbox.email}; the initial import has started.")
    return redirect("gmail:dashboard")


@login_required
def sync(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    mailbox = GmailMailbox.objects.filter(user=request.user).first()
    if mailbox and mailbox.status == GmailMailbox.Status.NEEDS_RECONNECT:
        messages.error(request, "Reconnect Gmail before syncing.")
    elif mailbox:
        sync_gmail_mailbox.delay(mailbox.pk)
    return redirect("gmail:dashboard")


@login_required
def status(request):
    mailbox = GmailMailbox.objects.filter(user=request.user).first()
    if not mailbox:
        return JsonResponse({"status": "disconnected"})
    run = mailbox.sync_runs.first()
    return JsonResponse(
        {
            "status": mailbox.status,
            "email": mailbox.email,
            "sync_error": mailbox.sync_error,
            "run": (
                {
                    "id": run.pk,
                    "status": run.status,
                    "discovered": run.discovered_count,
                    "processed": run.processed_count,
                    "created": run.created_count,
                    "updated": run.updated_count,
                    "deleted": run.deleted_count,
                }
                if run
                else None
            ),
        }
    )


@login_required
def disconnect(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    GmailMailbox.objects.filter(user=request.user).delete()
    messages.success(request, "The local Gmail connection and imported messages were deleted.")
    return redirect("gmail:dashboard")
