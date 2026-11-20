import datetime as dt

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.issues.models import Issue
from apps.projects.models import Project
from apps.workspaces.models import Membership, Workspace

from .burndown import burndown
from .models import Cycle

User = get_user_model()


def at(day, hour=12):
    return timezone.make_aware(dt.datetime.combine(day, dt.time(hour)))


class BurndownTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="bd", email="bd@example.com", password="pw")
        self.outsider = User.objects.create_user(username="bd-out", email="bdout@example.com", password="pw")
        self.workspace = Workspace.objects.create(name="BD", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role="owner")
        self.project = Project.objects.create(workspace=self.workspace, name="P", owner=self.owner)
        self.start = dt.date(2026, 11, 2)
        self.cycle = Cycle.objects.create(project=self.project, name="S1", start_date=self.start, end_date=self.start + dt.timedelta(days=4))

    def issue(self, estimate=None, done_on=None):
        issue = Issue.objects.create(project=self.project, title="i", reporter=self.owner, cycle=self.cycle, estimate=estimate)
        if done_on:
            Issue.objects.filter(pk=issue.pk).update(status="done", completed_at=at(done_on))
        return issue

    def test_counts_points_left_at_the_end_of_each_day(self):
        self.issue(estimate=5, done_on=self.start + dt.timedelta(days=1))
        self.issue(estimate=3, done_on=self.start + dt.timedelta(days=3))
        self.issue(estimate=2)
        self.issue()  # no estimate: counts as zero once the cycle is measured in points
        result = burndown(self.cycle, today=self.start + dt.timedelta(days=3))
        self.assertEqual(result["unit"], "points")
        self.assertEqual(result["total"], 10)
        self.assertEqual([d["remaining"] for d in result["days"]], [10, 5, 5, 2, None])
        self.assertEqual([d["ideal"] for d in result["days"]], [10, 7.5, 5, 2.5, 0])
        self.assertEqual(result["days"][0]["date"], "2026-11-02")

    def test_counts_issues_when_nothing_is_estimated(self):
        self.issue(done_on=self.start)
        self.issue()
        result = burndown(self.cycle, today=self.start + dt.timedelta(days=10))
        self.assertEqual(result["unit"], "issues")
        self.assertEqual([d["remaining"] for d in result["days"]], [1, 1, 1, 1, 1])

    def test_endpoint_is_for_workspace_members(self):
        url = reverse("cycle-burndown", args=[self.cycle.id])
        client = APIClient()
        client.force_authenticate(self.outsider)
        self.assertEqual(client.get(url).status_code, 404)
        client.force_authenticate(self.owner)
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["days"]), 5)


class EstimateTests(TestCase):
    def test_estimate_is_optional_and_bounded(self):
        owner = User.objects.create_user(username="est", email="est@example.com", password="pw")
        workspace = Workspace.objects.create(name="E", owner=owner)
        Membership.objects.create(workspace=workspace, user=owner, role="owner")
        project = Project.objects.create(workspace=workspace, name="P", owner=owner)
        client = APIClient()
        client.force_authenticate(owner)
        created = client.post(reverse("issue-list"), {"project": project.id, "title": "t", "estimate": 5}, format="json")
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data["estimate"], 5)
        url = reverse("issue-detail", args=[created.data["id"]])
        self.assertEqual(client.patch(url, {"estimate": 101}, format="json").status_code, 400)
        self.assertEqual(client.patch(url, {"estimate": -1}, format="json").status_code, 400)
        self.assertIsNone(client.patch(url, {"estimate": None}, format="json").data["estimate"])
