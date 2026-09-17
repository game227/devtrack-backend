import json

from django.contrib.auth import get_user_model
from django.core import signing
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from .models import TelegramAccount

User = get_user_model()
WEBHOOK_SECRET = "test-telegram-secret"


class TelegramLinkFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="linkuser", email="linkuser@example.com", password="pw"
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    @override_settings(TELEGRAM_BOT_USERNAME="devtrack_test_bot")
    def test_connect_returns_signed_deep_link(self):
        response = self.client.get(reverse("telegram-connect"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("https://t.me/devtrack_test_bot?start=", response.data["deep_link"])

    def test_status_defaults_to_not_connected(self):
        response = self.client.get(reverse("telegram-status"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"connected": False})

    def test_status_reflects_linked_account(self):
        TelegramAccount.objects.create(user=self.user, chat_id=555, telegram_username="linkuser_tg")
        response = self.client.get(reverse("telegram-status"))
        self.assertTrue(response.data["connected"])
        self.assertEqual(response.data["telegram_username"], "linkuser_tg")

    def test_disconnect_removes_account(self):
        TelegramAccount.objects.create(user=self.user, chat_id=555, telegram_username="linkuser_tg")
        response = self.client.delete(reverse("telegram-disconnect"))
        self.assertEqual(response.status_code, 204)
        self.assertFalse(TelegramAccount.objects.filter(user=self.user).exists())


@override_settings(TELEGRAM_WEBHOOK_SECRET=WEBHOOK_SECRET, TELEGRAM_BOT_TOKEN="")
class TelegramWebhookTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="webhookuser", email="webhookuser@example.com", password="pw"
        )
        self.url = reverse("telegram-webhook")
        self.client = APIClient()

    def post_update(self, body, secret=WEBHOOK_SECRET):
        return self.client.post(
            self.url,
            data=json.dumps(body),
            content_type="application/json",
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=secret,
        )

    def test_wrong_secret_rejected(self):
        response = self.post_update({"message": {}}, secret="wrong")
        self.assertEqual(response.status_code, 403)

    def test_empty_secret_setting_always_rejects(self):
        with override_settings(TELEGRAM_WEBHOOK_SECRET=""):
            response = self.post_update({"message": {}}, secret="")
        self.assertEqual(response.status_code, 403)

    def test_non_start_message_is_ignored(self):
        response = self.post_update(
            {"message": {"chat": {"id": 1}, "from": {"username": "x"}, "text": "hello"}}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(TelegramAccount.objects.count(), 0)

    def test_valid_start_token_links_account(self):
        token = signing.dumps({"user_id": self.user.id}, salt="telegram-link")
        response = self.post_update(
            {
                "message": {
                    "chat": {"id": 4242},
                    "from": {"username": "webhookuser_tg"},
                    "text": f"/start {token}",
                }
            }
        )
        self.assertEqual(response.status_code, 200)
        account = TelegramAccount.objects.get(user=self.user)
        self.assertEqual(account.chat_id, 4242)
        self.assertEqual(account.telegram_username, "webhookuser_tg")

    def test_relinking_chat_moves_it_to_the_new_user(self):
        other_user = User.objects.create_user(
            username="otheruser", email="otheruser@example.com", password="pw"
        )
        TelegramAccount.objects.create(user=other_user, chat_id=4242, telegram_username="old")

        token = signing.dumps({"user_id": self.user.id}, salt="telegram-link")
        self.post_update(
            {"message": {"chat": {"id": 4242}, "from": {"username": "new"}, "text": f"/start {token}"}}
        )

        self.assertFalse(TelegramAccount.objects.filter(user=other_user).exists())
        self.assertEqual(TelegramAccount.objects.get(chat_id=4242).user, self.user)

    def test_expired_or_tampered_token_does_not_link(self):
        response = self.post_update(
            {"message": {"chat": {"id": 999}, "from": {"username": "x"}, "text": "/start garbage"}}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(TelegramAccount.objects.count(), 0)
