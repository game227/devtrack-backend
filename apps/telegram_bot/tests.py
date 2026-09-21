from unittest.mock import patch

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from . import services
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


class BotServiceUnreachableTests(TestCase):
    """The bot is a separate service; when it is down nothing should 500."""

    def setUp(self):
        self.user = User.objects.create_user(username="tgdown", email="tgdown@example.com", password="pw")
        self.client = APIClient()

    @patch("apps.telegram_bot.services.requests.request", side_effect=requests.ConnectionError("refused"))
    def test_services_wrap_network_errors(self, _request):
        with self.assertRaises(services.BotServiceError):
            services.send_message(1, "hi")
        with self.assertRaises(services.BotServiceError):
            services.get_status(1)
        with self.assertRaises(services.BotServiceError):
            services.delete_link(1)

    @patch("apps.telegram_bot.services.requests.request", side_effect=requests.Timeout("slow"))
    def test_status_endpoint_reports_not_connected_instead_of_500(self, _request):
        self.client.force_authenticate(self.user)
        response = self.client.get(reverse("telegram-status"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"connected": False})

    @patch("apps.telegram_bot.services.requests.request", side_effect=requests.ConnectionError("refused"))
    def test_password_reset_falls_back_to_email_when_the_bot_is_down(self, _request):
        from django.core import mail

        response = self.client.post(reverse("password_reset"), {"email": self.user.email}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

    @patch("apps.telegram_bot.services.requests.request")
    def test_non_json_error_bodies_do_not_crash(self, mock_request):
        mock_request.return_value.status_code = 502
        mock_request.return_value.json.side_effect = ValueError("not json")
        with self.assertRaises(services.BotServiceError):
            services.send_message(1, "hi")
