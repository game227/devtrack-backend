import datetime as dt

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.issues.models import Issue
from apps.workspaces.models import Workspace

from .models import DemoAccount
from .views import DemoStartThrottle

User = get_user_model()


class DemoOffTests(TestCase):
    def test_off_by_default(self):
        self.assertEqual(APIClient().post(reverse("demo-start")).status_code, 404)
        self.assertFalse(User.objects.exists())


@override_settings(DEMO_ENABLED=True, DEMO_MAX_ACTIVE=3)
class DemoTests(TestCase):
    def start(self):
        response = APIClient().post(reverse("demo-start"))
        self.assertEqual(response.status_code, 201, response.data)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        return client, response.data

    def test_a_visitor_gets_a_signed_in_account_with_a_sample_workspace(self):
        client, data = self.start()
        me = client.get(reverse("me")).data
        self.assertRegex(me["username"], r"^demo-[0-9a-f]{8}$")
        workspace = Workspace.objects.get(pk=data["workspace"])
        self.assertEqual(workspace.owner.username, me["username"])
        self.assertEqual(Issue.objects.filter(project__workspace=workspace).count(), 10)
        issues = client.get(reverse("issue-list"), {"workspace": workspace.pk}).data
        self.assertEqual(issues["count"], 10)
        # Ordinary work is allowed.
        project = workspace.projects.get()
        created = client.post(reverse("issue-list"), {"project": project.pk, "title": "My first issue"}, format="json")
        self.assertEqual(created.status_code, 201)
        self.assertFalse(User.objects.get(username=me["username"]).has_usable_password())

    def test_outward_actions_are_blocked(self):
        client, data = self.start()
        issue = Issue.objects.filter(project__workspace_id=data["workspace"]).first()
        for method, url in [
            ("post", f"/api/v1/workspaces/{data['workspace']}/members/"),
            ("post", f"/api/v1/workspaces/{data['workspace']}/transfer-ownership/"),
            ("post", f"/api/v1/issues/{issue.pk}/attachments/"),
            ("post", "/api/v1/auth/password/change/"),
            ("post", "/api/v1/auth/email/verify/resend/"),
            ("post", "/api/v1/auth/2fa/setup/"),
            ("patch", "/api/v1/auth/me/"),
            ("get", "/api/v1/integrations/github/connect/"),
            ("post", "/api/v1/telegram/connect/"),
        ]:
            response = getattr(client, method)(url, {}, format="json")
            self.assertEqual(response.status_code, 403, url)
            self.assertEqual(response.data["detail"], "This is not available in the demo.")
        self.assertEqual(client.get(f"/api/v1/workspaces/{data['workspace']}/members/").status_code, 200)

    def test_demo_rules_do_not_touch_real_accounts(self):
        user = User.objects.create_user(username="real", email="real@example.com", password="pw")
        client = APIClient()
        client.force_authenticate(user)
        self.assertEqual(client.patch(reverse("me"), {"first_name": "Real"}, format="json").status_code, 200)

    def test_expired_demos_are_deleted_with_their_data(self):
        _, data = self.start()
        self.assertEqual(DemoAccount.objects.count(), 3)
        DemoAccount.objects.update(expires_at=timezone.now() - dt.timedelta(minutes=1))
        call_command("cleanup_demo", stdout=open("/dev/null", "w"))
        self.assertFalse(User.objects.exists())
        self.assertFalse(Workspace.objects.filter(pk=data["workspace"]).exists())
        self.assertFalse(Issue.objects.exists())

    def test_the_number_of_live_demos_is_capped(self):
        for _ in range(3):
            self.start()
        self.assertEqual(APIClient().post(reverse("demo-start")).status_code, 503)

    def test_starting_is_throttled(self):
        original = DemoStartThrottle.THROTTLE_RATES
        DemoStartThrottle.THROTTLE_RATES = {**original, "demo_start": "1/hour"}
        self.addCleanup(setattr, DemoStartThrottle, "THROTTLE_RATES", original)
        from django.core.cache import cache

        cache.clear()
        self.start()
        self.assertEqual(APIClient().post(reverse("demo-start")).status_code, 429)
