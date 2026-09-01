from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user("person", password="password")  # noqa: S106


def test_dashboard_requires_login(client):
    response = client.get(reverse("gmail:dashboard"))
    assert response.status_code == 302


def test_connect_stores_oauth_state_and_pkce(client, user, settings, monkeypatch):
    settings.GOOGLE_CLIENT_ID = "client-id"
    settings.GOOGLE_CLIENT_SECRET = "client-secret"  # noqa: S105
    flow = Mock(code_verifier="verifier")
    flow.authorization_url.return_value = ("https://accounts.google.com/o/oauth", "state")
    monkeypatch.setattr("gmail_integration.views._flow", lambda request: flow)
    client.force_login(user)
    response = client.get(reverse("gmail:connect"))
    assert response.status_code == 302
    assert client.session["gmail_oauth_state"] == "state"
    assert client.session["gmail_oauth_code_verifier"] == "verifier"


def test_callback_rejects_wrong_state(client, user):
    client.force_login(user)
    session = client.session
    session["gmail_oauth_state"] = "expected"
    session["gmail_oauth_code_verifier"] = "verifier"
    session.save()
    response = client.get(reverse("gmail:callback"), {"state": "wrong", "code": "code"})
    assert response.status_code == 302
