from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.cycles.models import Cycle
from apps.milestones.models import Milestone
from apps.projects.models import Label, Project
from apps.workspaces.models import Membership, Workspace

from .models import Issue

User = get_user_model()


class IssueListCreateViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="iowner", email="iowner@example.com", password="pw")
        self.member = User.objects.create_user(username="imember", email="imember@example.com", password="pw")
        self.outsider = User.objects.create_user(
            username="ioutsider", email="ioutsider@example.com", password="pw"
        )
        self.workspace = Workspace.objects.create(name="IWS", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role=Membership.Role.OWNER)
        Membership.objects.create(workspace=self.workspace, user=self.member, role=Membership.Role.MEMBER)
        self.project = Project.objects.create(workspace=self.workspace, name="P", owner=self.owner)
        self.other_project = Project.objects.create(workspace=self.workspace, name="Other", owner=self.owner)
        self.issue = Issue.objects.create(project=self.project, title="Existing", reporter=self.owner)
        self.url = reverse("issue-list")
        self.client = APIClient()

    def test_requires_project_or_workspace_param(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 400)

    def test_outsider_cannot_list_by_project(self):
        self.client.force_authenticate(self.outsider)
        response = self.client.get(self.url, {"project": self.project.id})
        self.assertEqual(response.status_code, 403)

    def test_member_can_list_by_project(self):
        self.client.force_authenticate(self.member)
        response = self.client.get(self.url, {"project": self.project.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_member_can_list_by_workspace_across_projects(self):
        Issue.objects.create(project=self.other_project, title="In other project", reporter=self.owner)
        self.client.force_authenticate(self.member)
        response = self.client.get(self.url, {"workspace": self.workspace.id})
        self.assertEqual(response.data["count"], 2)

    def test_create_sets_reporter_to_requesting_user(self):
        self.client.force_authenticate(self.member)
        response = self.client.post(
            self.url, {"project": self.project.id, "title": "New bug", "type": "bug"}, format="json"
        )
        self.assertEqual(response.status_code, 201)
        issue = Issue.objects.get(pk=response.data["id"])
        self.assertEqual(issue.reporter, self.member)

    def test_outsider_cannot_create(self):
        self.client.force_authenticate(self.outsider)
        response = self.client.post(self.url, {"project": self.project.id, "title": "Nope"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_filter_by_status(self):
        Issue.objects.create(project=self.project, title="Done one", status=Issue.Status.DONE, reporter=self.owner)
        self.client.force_authenticate(self.owner)
        response = self.client.get(self.url, {"project": self.project.id, "status": "done"})
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["title"], "Done one")

    def test_filter_by_assignee_me(self):
        Issue.objects.create(project=self.project, title="Mine", assignee=self.member, reporter=self.owner)
        self.client.force_authenticate(self.member)
        response = self.client.get(self.url, {"project": self.project.id, "assignee": "me"})
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["title"], "Mine")

    def test_filter_by_label(self):
        label = Label.objects.create(workspace=self.workspace, name="bug", color="#f00")
        labeled = Issue.objects.create(project=self.project, title="Labeled", reporter=self.owner)
        labeled.labels.add(label)
        self.client.force_authenticate(self.owner)
        response = self.client.get(self.url, {"project": self.project.id, "label": label.id})
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["title"], "Labeled")

    def test_filter_by_cycle_and_milestone(self):
        cycle = Cycle.objects.create(
            project=self.project, name="C1", start_date="2026-01-01", end_date="2026-01-14"
        )
        milestone = Milestone.objects.create(project=self.project, name="M1")
        matched = Issue.objects.create(
            project=self.project, title="Scoped", reporter=self.owner, cycle=cycle, milestone=milestone
        )
        self.client.force_authenticate(self.owner)
        response = self.client.get(self.url, {"project": self.project.id, "cycle": cycle.id})
        self.assertEqual([r["id"] for r in response.data["results"]], [matched.id])
        response = self.client.get(self.url, {"project": self.project.id, "milestone": milestone.id})
        self.assertEqual([r["id"] for r in response.data["results"]], [matched.id])


class IssueDetailViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="downer2", email="downer2@example.com", password="pw")
        self.reporter = User.objects.create_user(
            username="dreporter", email="dreporter@example.com", password="pw"
        )
        self.member = User.objects.create_user(username="dmember2", email="dmember2@example.com", password="pw")
        self.workspace = Workspace.objects.create(name="IDWS", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role=Membership.Role.OWNER)
        Membership.objects.create(workspace=self.workspace, user=self.reporter, role=Membership.Role.MEMBER)
        Membership.objects.create(workspace=self.workspace, user=self.member, role=Membership.Role.MEMBER)
        self.project = Project.objects.create(workspace=self.workspace, name="P", owner=self.owner)
        self.issue = Issue.objects.create(project=self.project, title="Bug", reporter=self.reporter)
        self.url = reverse("issue-detail", kwargs={"pk": self.issue.pk})
        self.client = APIClient()

    def test_any_workspace_member_can_view_and_update(self):
        self.client.force_authenticate(self.member)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        response = self.client.patch(self.url, {"status": "in_progress"}, format="json")
        self.assertEqual(response.status_code, 200)

    def test_reporter_can_delete(self):
        self.client.force_authenticate(self.reporter)
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, 204)

    def test_admin_can_delete_someone_elses_issue(self):
        self.client.force_authenticate(self.owner)
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, 204)

    def test_plain_member_cannot_delete_someone_elses_issue(self):
        self.client.force_authenticate(self.member)
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, 403)

    def test_assigning_sets_assignee(self):
        self.client.force_authenticate(self.reporter)
        response = self.client.patch(self.url, {"assignee_id": self.member.id}, format="json")
        self.assertEqual(response.status_code, 200)
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.assignee, self.member)
