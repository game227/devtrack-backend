import datetime as dt

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.issues.models import Issue
from apps.projects.models import Project
from apps.workspaces.models import Membership, Workspace

from .models import Cycle

User = get_user_model()


class CycleSerializerFieldsTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="cyowner", email="cyowner@example.com", password="pw")
        self.workspace = Workspace.objects.create(name="CYWS", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role=Membership.Role.OWNER)
        self.project = Project.objects.create(workspace=self.workspace, name="P", owner=self.owner)
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def test_completion_stats_and_is_active(self):
        today = dt.date.today()
        cycle = Cycle.objects.create(
            project=self.project, name="Active", start_date=today - dt.timedelta(days=1),
            end_date=today + dt.timedelta(days=1),
        )
        Issue.objects.create(project=self.project, title="A", reporter=self.owner, cycle=cycle, status=Issue.Status.DONE)
        Issue.objects.create(project=self.project, title="B", reporter=self.owner, cycle=cycle)

        response = self.client.get(reverse("cycle-detail", kwargs={"pk": cycle.pk}))
        self.assertEqual(response.data["issue_count"], 2)
        self.assertEqual(response.data["completed_count"], 1)
        self.assertEqual(response.data["completion_percent"], 50)
        self.assertTrue(response.data["is_active"])

    def test_past_cycle_is_not_active(self):
        today = dt.date.today()
        cycle = Cycle.objects.create(
            project=self.project, name="Past", start_date=today - dt.timedelta(days=20),
            end_date=today - dt.timedelta(days=10),
        )
        response = self.client.get(reverse("cycle-detail", kwargs={"pk": cycle.pk}))
        self.assertFalse(response.data["is_active"])

    def test_completion_percent_with_no_issues_is_zero(self):
        cycle = Cycle.objects.create(
            project=self.project, name="Empty", start_date="2026-01-01", end_date="2026-01-14"
        )
        response = self.client.get(reverse("cycle-detail", kwargs={"pk": cycle.pk}))
        self.assertEqual(response.data["completion_percent"], 0)


class CycleListCreateViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="cylowner", email="cylowner@example.com", password="pw")
        self.outsider = User.objects.create_user(
            username="cyloutsider", email="cyloutsider@example.com", password="pw"
        )
        self.workspace = Workspace.objects.create(name="CYLWS", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role=Membership.Role.OWNER)
        self.project = Project.objects.create(workspace=self.workspace, name="P", owner=self.owner)
        self.url = reverse("cycle-list")
        self.client = APIClient()

    def test_requires_project_param(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 400)

    def test_outsider_cannot_list_or_create(self):
        self.client.force_authenticate(self.outsider)
        response = self.client.get(self.url, {"project": self.project.id})
        self.assertEqual(response.status_code, 403)
        response = self.client.post(
            self.url,
            {"project": self.project.id, "name": "S1", "start_date": "2026-01-01", "end_date": "2026-01-14"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_member_can_create_a_cycle(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            self.url,
            {"project": self.project.id, "name": "Sprint 1", "start_date": "2026-01-01", "end_date": "2026-01-14"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(Cycle.objects.filter(project=self.project, name="Sprint 1").exists())
