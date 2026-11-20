from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.adminui.templatetags.devtrack_admin import devtrack_overview
from apps.issues.models import Issue
from apps.projects.models import Project
from apps.workspaces.models import Workspace

User = get_user_model()


class AdminUITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = User.objects.create_superuser(username="root", email="root@example.com", password="pw-for-tests-only")
        cls.root.totp_secret = "JBSWY3DPEHPK3PXP"  # must never appear on an admin page
        cls.root.save()
        cls.workspace = Workspace.objects.create(name="Nova", slug="nova", owner=cls.root)
        cls.project = Project.objects.create(workspace=cls.workspace, name="Payments", owner=cls.root, status=Project.Status.ACTIVE)
        Issue.objects.create(project=cls.project, title="Open one", reporter=cls.root, status=Issue.Status.IN_PROGRESS)
        Issue.objects.create(project=cls.project, title="Finished", reporter=cls.root, status=Issue.Status.DONE)

    def setUp(self):
        self.client.force_login(self.root)

    def test_sign_in_page_is_dressed_and_keeps_djangos_form(self):
        self.client.logout()
        response = self.client.get(reverse("admin:login"))
        self.assertContains(response, "devtrack_admin/admin.css")
        self.assertContains(response, 'id="login-form"')
        self.assertContains(response, 'name="username"')
        self.assertContains(response, "csrfmiddlewaretoken")

    def test_front_page_shows_the_overview_and_names_the_site(self):
        response = self.client.get(reverse("admin:index"))
        self.assertContains(response, "Issues on the line")
        self.assertContains(response, "dt-st-in_progress")
        self.assertContains(response, "<title>Overview · DevTrack admin</title>", html=False)
        self.assertEqual(admin.site.site_url, "http://localhost:5173")

    def test_overview_counts_and_links(self):
        overview = devtrack_overview()
        figures = {figure["label"]: figure for figure in overview["figures"]}
        self.assertEqual(figures["Issues"]["value"], 2)
        self.assertEqual(figures["Projects"]["note"], "1 active")
        stations = {station["key"]: station for station in overview["stations"]}
        self.assertEqual(stations["in_progress"]["count"], 1)
        self.assertEqual(stations["done"]["count"], 1)
        self.assertEqual(stations["todo"]["count"], 0)
        self.assertTrue(stations["done"]["url"].endswith("?status__exact=done"))
        # The station links really filter the list.
        response = self.client.get(stations["in_progress"]["url"])
        self.assertContains(response, "Open one")
        self.assertNotContains(response, "Finished")

    def test_every_registered_list_and_add_page_opens(self):
        for model, model_admin in admin.site._registry.items():
            opts = model._meta
            with self.subTest(model=opts.label):
                changelist = self.client.get(reverse(f"admin:{opts.app_label}_{opts.model_name}_changelist"))
                self.assertEqual(changelist.status_code, 200)
                if model_admin.has_add_permission(type("R", (), {"user": self.root})()):
                    add = self.client.get(reverse(f"admin:{opts.app_label}_{opts.model_name}_add"))
                    self.assertEqual(add.status_code, 200)

    def test_issue_list_shows_status_chips_and_change_page_opens(self):
        response = self.client.get(reverse("admin:issues_issue_changelist"))
        self.assertContains(response, 'class="dt-chip dt-st-in_progress"')
        issue = Issue.objects.get(title="Open one")
        self.assertEqual(self.client.get(reverse("admin:issues_issue_change", args=[issue.pk])).status_code, 200)

    def test_secrets_never_reach_an_admin_page(self):
        response = self.client.get(reverse("admin:accounts_user_change", args=[self.root.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "JBSWY3DPEHPK3PXP")
        self.assertNotContains(response, "totp_secret")
        self.assertNotContains(response, "totp_recovery_codes")

    def test_logs_are_read_only(self):
        for name in ("activities_activity", "notifications_notification"):
            with self.subTest(model=name):
                self.assertEqual(self.client.get(reverse(f"admin:{name}_add")).status_code, 403)
