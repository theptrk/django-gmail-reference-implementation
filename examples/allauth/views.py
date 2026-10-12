from allauth.socialaccount.adapter import get_adapter
from allauth.socialaccount.models import SocialAccount, SocialToken
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def dashboard(request):
    account = SocialAccount.objects.filter(user=request.user, provider="google").first()
    token = SocialToken.objects.filter(account=account).first() if account else None
    return render(
        request,
        "allauth_example/dashboard.html",
        {
            "google_configured": bool(get_adapter().list_apps(request, provider="google")),
            "google_account": account,
            "has_refresh_token": bool(token and token.token_secret),
            "gmail_scope": "https://www.googleapis.com/auth/gmail.readonly",
        },
    )
