from django.urls import path

from .views import TelegramConnectView, TelegramDisconnectView, TelegramStatusView

urlpatterns = [
    path("connect/", TelegramConnectView.as_view(), name="telegram-connect"),
    path("status/", TelegramStatusView.as_view(), name="telegram-status"),
    path("disconnect/", TelegramDisconnectView.as_view(), name="telegram-disconnect"),
]
