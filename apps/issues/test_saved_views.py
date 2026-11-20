from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.projects.models import Label, Project
from apps.workspaces.models import Membership, Workspace

from .models import SavedView
from .serializers import MAX_SAVED_VIEWS_PER_LIST

User = get_user_model()


class SavedViewTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_user(username="sv-me", email="svme@example.com", password="pw")
        self.colleague = User.objects.create_user(username="sv-col", email="svcol@example.com", password="pw")
        self.outsider = User.objects.create_user(username="sv-out", email="svout@example.com", password="pw")
        self.workspace = Workspace.objects.create(name="SV", owner=self.me)
        Membership.objects.create(workspace=self.workspace, user=self.me, role=Membership.Role.OWNER)
        Membership.objects.create(workspace=self.workspace, user=self.colleague, role=Membership.Role.MEMBER)
        self.project = Project.objects.create(workspace=self.workspace, name="P1", owner=self.me)
        self.project2 = Project.objects.create(workspace=self.workspace, name="P2", owner=self.me)
        self.elsewhere = Workspace.objects.create(name="Other", owner=self.outsider)
        Membership.objects.create(workspace=self.elsewhere, user=self.outsider, role=Membership.Role.OWNER)
        self.list_url = reverse("saved-view-list")
        self.client = APIClient()
        self.client.force_authenticate(self.me)

    def create(self, **body):
        return self.client.post(self.list_url, {"project": self.project.id, "name": "Bugs", "filters": {"type": "bug"}, **body}, format="json")

    def test_create_and_list_my_views_for_one_list(self):
        response = self.create(filters={"type": "bug", "status": "todo", "assignee": "me", "priority": ""})
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["filters"], {"type": "bug", "status": "todo", "assignee": "me"})
        self.assertEqual(response.data["workspace"], self.workspace.id)
        self.assertEqual(response.data["project"], self.project.id)
        self.client.post(self.list_url, {"workspace": self.workspace.id, "name": "Mine", "filters": {"assignee": "me"}}, format="json")

        project_views = self.client.get(self.list_url, {"project": self.project.id}).data
        self.assertEqual([view["name"] for view in project_views], ["Bugs"])
        workspace_views = self.client.get(self.list_url, {"workspace": self.workspace.id}).data
        self.assertEqual([view["name"] for view in workspace_views], ["Mine"])
        self.assertEqual(self.client.get(self.list_url, {"project": self.project2.id}).data, [])

    def test_views_are_private(self):
        view_id = self.create().data["id"]
        self.client.force_authenticate(self.colleague)
        self.assertEqual(self.client.get(self.list_url, {"project": self.project.id}).data, [])
        detail = reverse("saved-view-detail", args=[view_id])
        self.assertEqual(self.client.get(detail).status_code, 404)
        self.assertEqual(self.client.patch(detail, {"name": "Mine now"}, format="json").status_code, 404)
        self.assertEqual(self.client.delete(detail).status_code, 404)
        self.assertTrue(SavedView.objects.filter(pk=view_id, name="Bugs").exists())

    def test_outsiders_cannot_save_or_list_views_in_a_workspace(self):
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.create().status_code, 403)
        self.assertEqual(self.client.get(self.list_url, {"workspace": self.workspace.id}).status_code, 403)
        self.assertEqual(self.client.get(self.list_url).status_code, 400)

    def test_filters_are_checked(self):
        foreign_label = Label.objects.create(workspace=self.elsewhere, name="x", color="#000000")
        other_project_label = Label.objects.create(workspace=self.workspace, project=self.project2, name="p2", color="#000000")
        own_label = Label.objects.create(workspace=self.workspace, name="ok", color="#000000")
        for filters in [
            {"sort": "-id"},
            {"status": "nope"},
            {"assignee": self.outsider.id},
            {"assignee": "abc"},
            {"label": foreign_label.id},
            {"label": other_project_label.id},
            ["status"],
        ]:
            response = self.create(name=f"v{len(str(filters))}", filters=filters)
            self.assertEqual(response.status_code, 400, filters)
        response = self.create(filters={"label": own_label.id, "assignee": self.colleague.id})
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["filters"], {"label": str(own_label.id), "assignee": str(self.colleague.id)})

    def test_names_are_unique_per_list_and_trimmed(self):
        self.assertEqual(self.create(name="  Bugs   this   week ").data["name"], "Bugs this week")
        duplicate = self.create(name="bugs THIS week")
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("name", duplicate.data)
        self.assertEqual(self.create(project=self.project2.id, name="Bugs this week").status_code, 201)
        self.assertEqual(self.create(name="   ").status_code, 400)

    def test_rename_change_and_delete(self):
        view_id = self.create().data["id"]
        detail = reverse("saved-view-detail", args=[view_id])
        response = self.client.patch(detail, {"name": "Open bugs", "filters": {"type": "bug", "status": "in_progress"}}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["name"], "Open bugs")
        self.assertEqual(response.data["filters"], {"type": "bug", "status": "in_progress"})
        self.assertEqual(self.client.patch(detail, {"name": "Open bugs"}, format="json").status_code, 200)
        self.assertEqual(self.client.delete(detail).status_code, 204)
        self.assertFalse(SavedView.objects.filter(pk=view_id).exists())

    def test_a_list_holds_a_limited_number_of_views(self):
        SavedView.objects.bulk_create(
            SavedView(owner=self.me, workspace=self.workspace, project=self.project, name=f"v{i}") for i in range(MAX_SAVED_VIEWS_PER_LIST)
        )
        response = self.create(name="one too many")
        self.assertEqual(response.status_code, 400)

    def test_malformed_bodies_are_rejected_cleanly(self):
        self.assertEqual(self.client.post(self.list_url, [1, 2], format="json").status_code, 400)
        self.assertEqual(self.client.post(self.list_url, {"project": "x", "name": "a", "filters": {}}, format="json").status_code, 400)
        self.assertEqual(self.client.post(self.list_url, {"project": 10**30, "name": "a", "filters": {}}, format="json").status_code, 400)
