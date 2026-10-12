from allauth.account.views import LogoutView
from django.contrib import admin
from django.urls import include, path

from . import views

urlpatterns = [
    path("", views.dashboard, name="allauth_example_dashboard"),
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    # The main reference's base.html reverses "logout". Keep that link using allauth.
    path("accounts/logout/", LogoutView.as_view(), name="logout"),
]
