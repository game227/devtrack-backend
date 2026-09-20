from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.issues.models import Issue
from apps.projects.models import Project
from apps.workspaces.models import Membership, Workspace

from .models import Milestone

User = get_user_model()


class MilestoneSerializerFieldsTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="mowner", email="mowner@example.com", password="pw")
        self.workspace = Workspace.objects.create(name="MWS", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role=Membership.Role.OWNER)
        self.project = Project.objects.create(workspace=self.workspace, name="P", owner=self.owner)
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def test_completion_stats(self):
        milestone = Milestone.objects.create(project=self.project, name="v1.0", target_date="2026-12-01")
        Issue.objects.create(project=self.project, title="A", reporter=self.owner, milestone=milestone, status=Issue.Status.DONE)
        Issue.objects.create(project=self.project, title="B", reporter=self.owner, milestone=milestone)
        Issue.objects.create(project=self.project, title="C", reporter=self.owner, milestone=milestone)

        response = self.client.get(reverse("milestone-detail", kwargs={"pk": milestone.pk}))
        self.assertEqual(response.data["issue_count"], 3)
        self.assertEqual(response.data["completed_count"], 1)
        self.assertEqual(response.data["completion_percent"], 33)

    def test_completion_percent_with_no_issues_is_zero(self):
        milestone = Milestone.objects.create(project=self.project, name="Empty")
        response = self.client.get(reverse("milestone-detail", kwargs={"pk": milestone.pk}))
        self.assertEqual(response.data["completion_percent"], 0)


class MilestoneListCreateViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="mlowner", email="mlowner@example.com", password="pw")
        self.outsider = User.objects.create_user(
            username="mloutsider", email="mloutsider@example.com", password="pw"
        )
        self.workspace = Workspace.objects.create(name="MLWS", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role=Membership.Role.OWNER)
        self.project = Project.objects.create(workspace=self.workspace, name="P", owner=self.owner)
        self.url = reverse("milestone-list")
        self.client = APIClient()

    def test_requires_project_param(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 400)

    def test_outsider_cannot_list_or_create(self):
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(self.url, {"project": self.project.id}).status_code, 403)
        self.assertEqual(
            self.client.post(self.url, {"project": self.project.id, "name": "v1"}, format="json").status_code,
            403,
        )

    def test_member_can_create_a_milestone(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            self.url, {"project": self.project.id, "name": "v1.0", "target_date": "2026-12-01"}, format="json"
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(Milestone.objects.filter(project=self.project, name="v1.0").exists())
