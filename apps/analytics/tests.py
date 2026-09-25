import datetime as dt

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
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
        self.assertEqual(response.data["score"], 100)
        self.assertEqual(response.data["factors"]["bug_rate"], 100)
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


class ProjectHealthDetailTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="phdowner", email="phdowner@example.com", password="pw")
        self.workspace = Workspace.objects.create(name="PHDWS", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role=Membership.Role.OWNER)
        self.project = Project.objects.create(workspace=self.workspace, name="Quiet", owner=self.owner)
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.url = reverse("project-health", kwargs={"pk": self.project.pk})

    def test_risks_are_also_reported_as_structured_details(self):
        today = dt.date.today()
        Issue.objects.create(
            project=self.project, title="Late", reporter=self.owner, due_date=today - dt.timedelta(days=5)
        )
        Issue.objects.create(
            project=self.project, title="Urgent bug", reporter=self.owner,
            type=Issue.Type.BUG, priority=Issue.Priority.URGENT,
        )
        details = {d["code"]: d for d in self.client.get(self.url).data["risk_details"]}
        self.assertEqual(details["overdue"]["count"], 1)
        self.assertEqual(details["urgent_bugs"]["count"], 1)

    def test_a_busy_sibling_project_does_not_hide_a_stalled_one(self):
        # Push the quiet project's own activity far into the past ...
        from apps.activities.models import Activity

        Activity.objects.filter(workspace=self.workspace).update(
            created_at=timezone.now() - dt.timedelta(days=30)
        )
        # ... then let a *different* project in the workspace be busy right now.
        self.project.status = Project.Status.ACTIVE  # activity is only judged for active projects
        self.project.save()
        busy = Project.objects.create(workspace=self.workspace, name="Busy", owner=self.owner)
        Issue.objects.create(project=busy, title="Fresh", reporter=self.owner)

        factors = self.client.get(self.url).data["factors"]
        self.assertEqual(factors["development_activity"], 0)


class DailyActivityTests(TestCase):
    """The profile chart needs every day of the window, including the quiet ones."""

    def setUp(self):
        from apps.activities.models import Activity

        self.Activity = Activity
        self.user = User.objects.create_user(username="dayuser", email="dayuser@example.com", password="pw")
        self.workspace = Workspace.objects.create(name="DAYWS", owner=self.user)
        Membership.objects.create(workspace=self.workspace, user=self.user, role=Membership.Role.OWNER)
        self.project = Project.objects.create(workspace=self.workspace, name="P", owner=self.user)
        Activity.objects.all().delete()  # creating the project logged one
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = reverse("developer-analytics", kwargs={"pk": self.user.pk})

    def log(self, days_ago, count=1):
        for _ in range(count):
            activity = self.Activity.objects.create(
                workspace=self.workspace, actor=self.user, verb="created_project", target=self.project
            )
            noon = timezone.make_aware(
                dt.datetime.combine(timezone.localdate() - dt.timedelta(days=days_ago), dt.time(12, 0))
            )
            self.Activity.objects.filter(pk=activity.pk).update(created_at=noon)

    def daily(self):
        return self.client.get(self.url, {"workspace": self.workspace.id}).data["daily_activity"]

    def test_every_day_of_the_window_is_present_oldest_first_ending_today(self):
        days = self.daily()
        self.assertEqual(len(days), 14)
        self.assertEqual(days[-1]["date"], timezone.localdate())
        self.assertEqual(days[0]["date"], timezone.localdate() - dt.timedelta(days=13))
        self.assertEqual([d["date"] for d in days], sorted(d["date"] for d in days))
        self.assertTrue(all(d["count"] == 0 for d in days))

    def test_quiet_days_are_zero_and_busy_days_are_counted(self):
        self.log(0, count=2)
        self.log(3)
        by_offset = {(timezone.localdate() - d["date"]).days: d["count"] for d in self.daily()}
        self.assertEqual(by_offset[0], 2)
        self.assertEqual(by_offset[3], 1)
        self.assertEqual(by_offset[1], 0)
        self.assertEqual(by_offset[13], 0)

    def test_activity_older_than_the_window_is_ignored(self):
        self.log(20)
        self.assertEqual(sum(d["count"] for d in self.daily()), 0)
