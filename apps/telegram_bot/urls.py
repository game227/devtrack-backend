from django.urls import path

from . import bot_api
from .views import TelegramConnectView, TelegramDisconnectView, TelegramStatusView

urlpatterns = [
    path("connect/", TelegramConnectView.as_view(), name="telegram-connect"),
    path("status/", TelegramStatusView.as_view(), name="telegram-status"),
    path("disconnect/", TelegramDisconnectView.as_view(), name="telegram-disconnect"),
    # Called by the bot service on a linked user's behalf (see bot_auth.py).
    path("bot/me/", bot_api.BotMeView.as_view(), name="bot-me"),
    path("bot/issues/", bot_api.BotIssuesView.as_view(), name="bot-issues"),
    path("bot/issues/<int:pk>/", bot_api.BotIssueDetailView.as_view(), name="bot-issue"),
    path("bot/issues/<int:pk>/status/", bot_api.BotIssueStatusView.as_view(), name="bot-issue-status"),
    path("bot/issues/<int:pk>/comments/", bot_api.BotIssueCommentView.as_view(), name="bot-issue-comment"),
    path("bot/projects/", bot_api.BotProjectsView.as_view(), name="bot-projects"),
    path("bot/projects/<int:pk>/health/", bot_api.BotProjectHealthView.as_view(), name="bot-project-health"),
]
