"""Run explicitly with --ds=examples.allauth.settings; no Google or Redis needed."""

from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import pytest
from allauth.socialaccount.models import SocialAccount, SocialToken
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


class Links(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.hrefs = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.hrefs.append(dict(attrs).get("href", ""))


@pytest.fixture
def user():
    return get_user_model().objects.create_user(
        "person",
        email="person@example.test",
        password="local-test-password",  # noqa: S106
    )


@pytest.fixture
def google(settings):
    settings.SOCIALACCOUNT_PROVIDERS = {
        "google": {
            "SCOPE": ["openid", "profile", "email"],
            "AUTH_PARAMS": {"access_type": "offline"},
            "OAUTH_PKCE_ENABLED": True,
            "APP": {"client_id": "test-client", "secret": "test-secret"},
        }
    }


def assert_styled(html):
    assert "font:16px system-ui" in html
    assert "<nav>" in html
    assert "<strong>Menu:</strong>" not in html


def connect_link(html):
    return next(href for href in Links(html).hrefs if "/accounts/google/login/" in href)


def test_dashboard_requires_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert response.url.startswith(reverse("account_login"))


def test_missing_credentials_have_an_explanation(client, user, settings):
    settings.SOCIALACCOUNT_PROVIDERS = {"google": {}}
    client.force_login(user)
    html = client.get("/").content.decode()
    assert_styled(html)
    assert "Google is not configured" in html
    assert "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET" in html
    assert not any("/accounts/google/login/" in href for href in Links(html).hrefs)


@pytest.mark.parametrize("page", ["account_login", "account_signup"])
def test_entrance_pages_use_the_host_layout(client, page):
    response = client.get(reverse(page))
    assert response.status_code == 200
    assert_styled(response.content.decode())


def test_connections_without_credentials_are_still_styled(client, user, settings):
    settings.SOCIALACCOUNT_PROVIDERS = {"google": {}}
    client.force_login(user)
    response = client.get(reverse("socialaccount_connections"))
    assert response.status_code == 200
    html = response.content.decode()
    assert_styled(html)
    assert "no third-party accounts connected" in html


def test_connect_confirmation_and_oauth_request(client, user, google):
    client.force_login(user)
    html = client.get("/").content.decode()
    assert "Connect Gmail" in html
    href = connect_link(html)
    params = parse_qs(urlsplit(href).query)
    assert params["process"] == ["connect"]
    assert params["auth_params"] == ["prompt=consent"]
    assert params["scope"] == ["https://www.googleapis.com/auth/gmail.readonly"]

    confirmation = client.get(href)
    assert confirmation.status_code == 200
    assert_styled(confirmation.content.decode())
    assert "Connect Google" in confirmation.content.decode()
    assert "csrfmiddlewaretoken" in confirmation.content.decode()

    response = client.post(href)
    assert response.status_code == 302
    oauth = parse_qs(urlsplit(response.url).query)
    assert urlsplit(response.url).hostname == "accounts.google.com"
    assert oauth["prompt"] == ["consent"]
    assert oauth["access_type"] == ["offline"]
    assert "https://www.googleapis.com/auth/gmail.readonly" in oauth["scope"][0].split()
    assert oauth["code_challenge_method"] == ["S256"]
    assert oauth["state"]
    assert oauth["redirect_uri"] == ["http://testserver/accounts/google/login/callback/"]


def test_plain_google_login_does_not_request_gmail_or_force_consent(client, google):
    response = client.post(reverse("google_login"))
    assert response.status_code == 302
    oauth = parse_qs(urlsplit(response.url).query)
    assert "prompt" not in oauth
    assert "https://www.googleapis.com/auth/gmail.readonly" not in oauth["scope"][0].split()


@pytest.mark.parametrize("refresh_token", [None, "", "stored-refresh-token"])
def test_linked_identity_and_offline_credentials_are_distinct(client, user, google, refresh_token):
    account = SocialAccount.objects.create(user=user, provider="google", uid="google-user")
    if refresh_token is not None:
        SocialToken.objects.create(
            account=account,
            token="access",  # noqa: S106
            token_secret=refresh_token,  # noqa: S106
        )
    client.force_login(user)
    html = client.get("/").content.decode()
    assert "Google identity linked" in html
    assert "Reconnect Gmail" in html
    assert parse_qs(urlsplit(connect_link(html)).query)["auth_params"] == ["prompt=consent"]
    if refresh_token:
        assert "does not prove Gmail permission" in html
    else:
        assert "Offline access is missing or was revoked" in html


def test_connection_removal_preserves_post_and_deletes_local_tokens(client, user, google):
    account = SocialAccount.objects.create(user=user, provider="google", uid="google-user")
    token = SocialToken.objects.create(
        account=account,
        token="access",  # noqa: S106
        token_secret="refresh",  # noqa: S106
    )
    client.force_login(user)
    url = reverse("socialaccount_connections")
    response = client.get(url)
    html = response.content.decode()
    assert_styled(html)
    assert "csrfmiddlewaretoken" in html
    assert 'name="account"' in html
    assert SocialAccount.objects.filter(pk=account.pk).exists()
    response = client.post(url, {"account": account.pk})
    assert response.status_code == 302
    assert not SocialAccount.objects.filter(pk=account.pk).exists()
    assert not SocialToken.objects.filter(pk=token.pk).exists()


def test_connection_removal_requires_csrf(user, google):
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    response = client.post(reverse("socialaccount_connections"), {"account": 1})
    assert response.status_code == 403


@pytest.mark.parametrize(
    "template", ["socialaccount/authentication_error.html", "socialaccount/login_cancelled.html"]
)
def test_error_pages_use_the_host_layout(client, template):
    request = client.get(reverse("account_login")).wsgi_request
    assert_styled(render_to_string(template, request=request))
