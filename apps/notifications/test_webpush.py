import json
from io import StringIO
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from pywebpush import WebPushException
from rest_framework.test import APIClient

from apps.issues.models import Issue
from apps.projects.models import Project
from apps.workspaces.models import Membership, Workspace

from .models import PushSubscription
from .webpush import allowed_endpoint

User = get_user_model()
KEYS = {"p256dh": "BPub", "auth": "secret"}
FCM = "https://fcm.googleapis.com/fcm/send/abc"
ON = {"WEB_PUSH_VAPID_PUBLIC_KEY": "pub", "WEB_PUSH_VAPID_PRIVATE_KEY": "priv"}


class EndpointTests(TestCase):
    def test_only_browser_push_services(self):
        for url in [FCM, "https://updates.push.services.mozilla.com/wpush/v2/x", "https://web.push.apple.com/abc", "https://db5p.notify.windows.com/w/?token=1"]:
            self.assertTrue(allowed_endpoint(url), url)
        for url in ["http://fcm.googleapis.com/x", "https://evil.test/x", "https://fcm.googleapis.com.evil.test/x", "https://localhost/x", "https://fcm.googleapis.com:8443/x"]:
            self.assertFalse(allowed_endpoint(url), url)


class SubscribeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="pu", email="pu@example.com", password="pw")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_off_without_keys(self):
        self.assertEqual(self.client.get(reverse("push-status")).data, {"enabled": False, "public_key": "", "subscriptions": 0})
        response = self.client.post(reverse("push-subscribe"), {"endpoint": FCM, "keys": KEYS}, format="json")
        self.assertEqual(response.status_code, 409)

    @override_settings(**ON)
    def test_subscribe_and_unsubscribe(self):
        self.assertEqual(self.client.get(reverse("push-status")).data["public_key"], "pub")
        response = self.client.post(reverse("push-subscribe"), {"endpoint": FCM, "keys": KEYS, "lang": "uz"}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(PushSubscription.objects.get().lang, "uz")
        # Subscribing again (or as someone else on the same browser) replaces, never duplicates.
        other = User.objects.create_user(username="pu2", email="pu2@example.com", password="pw")
        self.client.force_authenticate(other)
        self.client.post(reverse("push-subscribe"), {"endpoint": FCM, "keys": KEYS}, format="json")
        self.assertEqual(PushSubscription.objects.get().user, other)
        self.client.post(reverse("push-unsubscribe"), {"endpoint": FCM}, format="json")
        self.assertFalse(PushSubscription.objects.exists())

    @override_settings(**ON)
    def test_refuses_other_hosts_and_bad_keys(self):
        bad = [{"endpoint": "https://evil.test/hook", "keys": KEYS}, {"endpoint": FCM, "keys": {"auth": "x"}}, {"endpoint": FCM, "keys": KEYS, "lang": "de"}]
        for body in bad:
            self.assertEqual(self.client.post(reverse("push-subscribe"), body, format="json").status_code, 400, body)


@override_settings(**ON, WEB_PUSH_SUBJECT="mailto:test@example.com")
class DeliveryTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="boss", email="boss@example.com", password="pw")
        self.dev = User.objects.create_user(username="dev", email="dev@example.com", password="pw")
        self.workspace = Workspace.objects.create(name="W", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role="owner")
        Membership.objects.create(workspace=self.workspace, user=self.dev, role="member")
        self.project = Project.objects.create(workspace=self.workspace, name="P", owner=self.owner)
        PushSubscription.objects.create(user=self.dev, endpoint=FCM, lang="ru", **KEYS)

    def assign(self):
        issue = Issue.objects.create(project=self.project, title="Fix login", reporter=self.owner)
        issue.assignee = self.dev
        issue._actor = self.owner
        issue.save()
        return issue

    @patch("pywebpush.webpush")
    def test_a_notification_reaches_the_browser_in_its_language(self, webpush):
        issue = self.assign()
        webpush.assert_called_once()
        kwargs = webpush.call_args.kwargs
        self.assertEqual(kwargs["subscription_info"]["endpoint"], FCM)
        self.assertEqual(kwargs["vapid_claims"], {"sub": "mailto:test@example.com"})
        data = json.loads(kwargs["data"])
        self.assertEqual(data["title"], "boss назначил(а) вам задачу")
        self.assertEqual(data["body"], "Fix login")
        self.assertEqual(data["url"], f"/issues/{issue.pk}")

    @patch("pywebpush.webpush")
    def test_gone_subscriptions_are_removed(self, webpush):
        webpush.side_effect = WebPushException("gone", response=MagicMock(status_code=410))
        self.assign()
        self.assertFalse(PushSubscription.objects.exists())

    @patch("pywebpush.webpush")
    def test_other_failures_keep_the_subscription_and_the_request(self, webpush):
        webpush.side_effect = WebPushException("busy", response=MagicMock(status_code=500))
        self.assign()
        self.assertTrue(PushSubscription.objects.exists())


class KeyCommandTests(TestCase):
    def test_prints_a_usable_pair(self):
        out = StringIO()
        call_command("generate_vapid_keys", stdout=out)
        lines = dict(line.split("=", 1) for line in out.getvalue().split())
        self.assertEqual(len(lines["WEB_PUSH_VAPID_PUBLIC_KEY"]), 87)
        self.assertEqual(len(lines["WEB_PUSH_VAPID_PRIVATE_KEY"]), 43)
