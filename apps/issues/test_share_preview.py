import datetime as dt

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.projects.models import Project
from apps.workspaces.models import Membership, Workspace

from .models import Issue, IssueShareLink

User = get_user_model()


@override_settings(FRONTEND_URL="https://app.test")
class SharePreviewTests(TestCase):
    def setUp(self):
        cache.clear()
        owner = User.objects.create_user(username="p-own", email="pown@example.com", password="pw")
        workspace = Workspace.objects.create(name="PW", owner=owner)
        Membership.objects.create(workspace=workspace, user=owner, role="owner")
        project = Project.objects.create(workspace=workspace, name="Payments <API>", owner=owner)
        self.issue = Issue.objects.create(
            project=project,
            title='Refund <script>alert("x")</script> returns 500',
            reporter=owner,
            status="in_progress",
            due_date=dt.date(2026, 11, 21),
        )
        self.link = IssueShareLink.objects.create(
            issue=self.issue, token="t" * 43, created_by=owner, expires_at=timezone.now() + dt.timedelta(days=7)
        )

    def test_preview_names_the_issue_for_chat_apps_and_sends_people_on(self):
        response = self.client.get(reverse("share-preview", args=[self.link.token]), {"lang": "uz"})
        self.assertEqual(response.status_code, 200)
        page = response.content.decode()
        # Escaped everywhere: the title is data, never markup.
        self.assertNotIn("<script>", page)
        self.assertIn('property="og:title" content="#1 Refund &lt;script&gt;', page)
        self.assertIn("Payments &lt;API&gt; · Jarayonda · Muddat: 2026-11-21", page)
        self.assertIn(f"/s/{self.link.token}/card.png?lang=uz", page)
        self.assertIn(f'url=https://app.test/share/{self.link.token}', page)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertIn("default-src 'none'", response["Content-Security-Policy"])

    def test_card_is_a_1200_by_630_png(self):
        from io import BytesIO

        from PIL import Image

        for lang in ("uz", "ru", "en"):
            response = self.client.get(reverse("share-card", args=[self.link.token]), {"lang": lang})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "image/png")
            self.assertEqual(Image.open(BytesIO(response.content)).size, (1200, 630))

    def test_a_revoked_or_expired_link_shows_nothing(self):
        self.link.revoked = True
        self.link.save(update_fields=["revoked"])
        response = self.client.get(reverse("share-preview", args=[self.link.token]))
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("Refund", response.content.decode())
        self.assertEqual(self.client.get(reverse("share-card", args=[self.link.token])).status_code, 404)
        self.assertEqual(self.client.get(reverse("share-preview", args=["nope"])).status_code, 404)
