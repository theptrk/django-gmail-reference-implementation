from django.urls import path

from . import views

app_name = "gmail"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("gmail/connect/", views.connect, name="connect"),
    path("gmail/callback/", views.callback, name="callback"),
    path("gmail/sync/", views.sync, name="sync"),
    path("gmail/status/", views.status, name="status"),
    path("gmail/disconnect/", views.disconnect, name="disconnect"),
]
