import datetime as dt

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.issues.models import Issue
from apps.projects.models import Project
from apps.workspaces.models import Membership, Workspace

User = get_user_model()


class DashboardViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="daowner", email="daowner@example.com", password="pw")
        self.outsider = User.objects.create_user(
            username="daoutsider", email="daoutsider@example.com", password="pw"
        )
        self.workspace = Workspace.objects.create(name="DAWS", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role=Membership.Role.OWNER)
        self.project = Project.objects.create(
            workspace=self.workspace, name="P", owner=self.owner, status=Project.Status.ACTIVE
        )
        Issue.objects.create(project=self.project, title="Done", reporter=self.owner, status=Issue.Status.DONE)
        Issue.objects.create(project=self.project, title="Open", reporter=self.owner)
        self.url = reverse("dashboard")
        self.client = APIClient()

    def test_requires_workspace_param(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 400)

    def test_outsider_forbidden(self):
        self.client.force_authenticate(self.outsider)
        response = self.client.get(self.url, {"workspace": self.workspace.id})
        self.assertEqual(response.status_code, 403)

    def test_summarizes_projects_and_issues(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get(self.url, {"workspace": self.workspace.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["projects"]["total"], 1)
        self.assertEqual(response.data["projects"]["active"], 1)
        self.assertEqual(response.data["issues"], {"total": 2, "open": 1, "done": 1})

    def test_upcoming_deadlines_flags_overdue(self):
        today = dt.date.today()
        Issue.objects.create(
            project=self.project, title="Overdue", reporter=self.owner, due_date=today - dt.timedelta(days=1)
        )
        self.client.force_authenticate(self.owner)
        response = self.client.get(self.url, {"workspace": self.workspace.id})
        overdue = [d for d in response.data["upcoming_deadlines"] if d["title"] == "Overdue"][0]
        self.assertTrue(overdue["is_overdue"])


class SearchViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="sowner", email="sowner@example.com", password="pw")
        self.workspace = Workspace.objects.create(name="SWS", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role=Membership.Role.OWNER)
        self.project = Project.objects.create(workspace=self.workspace, name="Payments Service", owner=self.owner)
        Issue.objects.create(project=self.project, title="Fix payments bug", reporter=self.owner)
        Issue.objects.create(project=self.project, title="Unrelated task", reporter=self.owner)
        self.url = reverse("search")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def test_requires_query_and_workspace(self):
        response = self.client.get(self.url, {"workspace": self.workspace.id})
        self.assertEqual(response.status_code, 400)
        response = self.client.get(self.url, {"q": "payments"})
        self.assertEqual(response.status_code, 400)

    def test_matches_projects_and_issues_case_insensitively(self):
        response = self.client.get(self.url, {"workspace": self.workspace.id, "q": "payments"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([p["name"] for p in response.data["projects"]], ["Payments Service"])
        self.assertEqual([i["title"] for i in response.data["issues"]], ["Fix payments bug"])


class ProjectHealthViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="phowner", email="phowner@example.com", password="pw")
        self.outsider = User.objects.create_user(
            username="phoutsider", email="phoutsider@example.com", password="pw"
        )
        self.workspace = Workspace.objects.create(name="PHWS", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role=Membership.Role.OWNER)
        self.project = Project.objects.create(workspace=self.workspace, name="P", owner=self.owner)
        self.url = reverse("project-health", kwargs={"pk": self.project.pk})
        self.client = APIClient()

    def test_outsider_forbidden(self):
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_project_with_no_issues_is_perfectly_healthy(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "healthy")
        self.assertEqual(response.data["factors"]["task_progress"], 100)
        self.assertEqual(response.data["risks"], [])

    def test_overdue_and_urgent_bugs_surface_as_risks(self):
        today = dt.date.today()
        Issue.objects.create(
            project=self.project, title="Late", reporter=self.owner,
            due_date=today - dt.timedelta(days=5),
        )
        Issue.objects.create(
            project=self.project, title="Urgent bug", reporter=self.owner,
            type=Issue.Type.BUG, priority=Issue.Priority.URGENT,
        )
        self.client.force_authenticate(self.owner)
        response = self.client.get(self.url)
        risks_text = " ".join(response.data["risks"])
        self.assertIn("past their due date", risks_text)
        self.assertIn("unresolved high/urgent priority bug", risks_text)


class DeveloperAnalyticsViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="devowner", email="devowner@example.com", password="pw")
        self.dev = User.objects.create_user(username="devuser", email="devuser@example.com", password="pw")
        self.outsider = User.objects.create_user(
            username="devoutsider", email="devoutsider@example.com", password="pw"
        )
        self.workspace = Workspace.objects.create(name="DEVWS", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role=Membership.Role.OWNER)
        Membership.objects.create(workspace=self.workspace, user=self.dev, role=Membership.Role.MEMBER)
        self.project = Project.objects.create(workspace=self.workspace, name="P", owner=self.owner)
        Issue.objects.create(
            project=self.project, title="Done by dev", reporter=self.owner, assignee=self.dev,
            status=Issue.Status.DONE,
        )
        Issue.objects.create(
            project=self.project, title="Open for dev", reporter=self.owner, assignee=self.dev,
        )
        self.url = reverse("developer-analytics", kwargs={"pk": self.dev.pk})
        self.client = APIClient()

    def test_requires_workspace_param(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 400)

    def test_requester_must_be_a_workspace_member(self):
        self.client.force_authenticate(self.outsider)
        response = self.client.get(self.url, {"workspace": self.workspace.id})
        self.assertEqual(response.status_code, 403)

    def test_target_must_be_a_workspace_member(self):
        other_workspace = Workspace.objects.create(name="OtherWS", owner=self.owner)
        Membership.objects.create(workspace=other_workspace, user=self.owner, role=Membership.Role.OWNER)
        self.client.force_authenticate(self.owner)
        response = self.client.get(self.url, {"workspace": other_workspace.id})
        self.assertEqual(response.status_code, 403)

    def test_counts_tasks_completed_and_open_assigned(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get(self.url, {"workspace": self.workspace.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["tasks_completed"], 1)
        self.assertEqual(response.data["open_assigned"], 1)
