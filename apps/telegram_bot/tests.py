from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from .services import BotServiceError

User = get_user_model()


@override_settings(TELEGRAM_BOT_USERNAME="gamma_v_bot", TELEGRAM_LINK_SECRET="test-link-secret")
class TelegramConnectViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="tguser", email="tguser@example.com", password="pw"
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_connect_returns_a_deep_link_for_the_configured_bot(self):
        response = self.client.get(reverse("telegram-connect"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["deep_link"].startswith("https://t.me/gamma_v_bot?start="))


class TelegramStatusViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="statususer", email="statususer@example.com", password="pw"
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    @patch("apps.telegram_bot.views.services.get_status")
    def test_status_reflects_bot_service_response(self, mock_get_status):
        mock_get_status.return_value = {"connected": True, "telegram_username": "alice", "linked_at": "now"}
        response = self.client.get(reverse("telegram-status"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["connected"])
        mock_get_status.assert_called_once_with(self.user.id)

    @patch("apps.telegram_bot.views.services.get_status")
    def test_status_defaults_to_not_connected_when_bot_service_errors(self, mock_get_status):
        mock_get_status.side_effect = BotServiceError("unreachable")
        response = self.client.get(reverse("telegram-status"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"connected": False})


class TelegramDisconnectViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="disconnectuser", email="disconnectuser@example.com", password="pw"
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    @patch("apps.telegram_bot.views.services.delete_link")
    def test_disconnect_calls_bot_service_and_returns_204(self, mock_delete_link):
        response = self.client.delete(reverse("telegram-disconnect"))
        self.assertEqual(response.status_code, 204)
        mock_delete_link.assert_called_once_with(self.user.id)

    @patch("apps.telegram_bot.views.services.delete_link")
    def test_disconnect_is_best_effort_if_bot_service_errors(self, mock_delete_link):
        mock_delete_link.side_effect = BotServiceError("unreachable")
        response = self.client.delete(reverse("telegram-disconnect"))
        self.assertEqual(response.status_code, 204)
