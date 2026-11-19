from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.projects.models import Project
from apps.telegram_bot.services import BotServiceError
from apps.workspaces.models import Workspace

from .digest import digest_data, digest_html, digest_text

User = get_user_model()


@override_settings(FRONTEND_URL="https://app.test")
class BrandedMailTests(TestCase):
    @patch("apps.accounts.views.telegram_services.send_message", side_effect=BotServiceError("not linked"))
    def test_password_reset_has_a_branded_html_part_with_the_same_link(self, _send):
        user = User.objects.create_user(username="mail_user", email="mail_user@example.com", password="pw")
        APIClient().post(reverse("password_reset"), {"email": user.email, "lang": "uz"}, format="json")
        message = mail.outbox[0]
        html, kind = message.alternatives[0]
        self.assertEqual(kind, "text/html")
        link = next(word for word in message.body.split() if "/reset-password/" in word)
        self.assertIn(f'href="{link}"', html)
        self.assertIn("Yangi parol o&#x27;rnatish", html)
        # The plain text still carries the link and says what to do if it was not you.
        self.assertIn("e'tiborsiz qoldiring", message.body)

    def test_weekly_summary_html_escapes_names(self):
        owner = User.objects.create_user(username="dig_owner", email="dig_owner@example.com", password="pw")
        workspace = Workspace.objects.create(name="<i>Labs</i>", owner=owner)
        Project.objects.create(workspace=workspace, name="<b>Shop</b>", owner=owner)
        data = digest_data(workspace)
        html, subject = digest_html(data, "en")
        self.assertEqual(subject, digest_text(data, "en")[0])
        self.assertNotIn("<b>Shop</b>", html)
        self.assertIn("&lt;b&gt;Shop&lt;/b&gt;", html)
        self.assertIn('href="https://app.test"', html)
