from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.telegram_bot.services import BotServiceError

User = get_user_model()


class PasswordResetChannelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="reset_user", email="reset_user@example.com", password="pw"
        )
        self.client = APIClient()
        self.url = reverse("password_reset")

    @patch("apps.accounts.views.telegram_services.send_message")
    def test_prefers_telegram_and_sends_no_email_when_it_succeeds(self, mock_send_message):
        mock_send_message.return_value = {"detail": "sent"}
        self.client.post(self.url, {"email": self.user.email}, format="json")
        mock_send_message.assert_called_once()
        self.assertEqual(mock_send_message.call_args[0][0], self.user.id)
        self.assertEqual(len(mail.outbox), 0)

    @patch("apps.accounts.views.telegram_services.send_message")
    def test_falls_back_to_email_when_telegram_is_not_linked_or_fails(self, mock_send_message):
        mock_send_message.side_effect = BotServiceError("not linked")
        self.client.post(self.url, {"email": self.user.email}, format="json")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])

    def test_unknown_email_sends_nothing_but_still_returns_200(self):
        response = self.client.post(self.url, {"email": "nobody@example.com"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
