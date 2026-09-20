from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.workspaces.models import Membership, Workspace

from .models import Label, Note, Project, ProjectMember

User = get_user_model()


class ProjectListCreateViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="powner", email="powner@example.com", password="pw")
        self.member = User.objects.create_user(username="pmember", email="pmember@example.com", password="pw")
        self.outsider = User.objects.create_user(
            username="poutsider", email="poutsider@example.com", password="pw"
        )
        self.workspace = Workspace.objects.create(name="PWS", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role=Membership.Role.OWNER)
        Membership.objects.create(workspace=self.workspace, user=self.member, role=Membership.Role.MEMBER)
        self.project = Project.objects.create(workspace=self.workspace, name="Existing", owner=self.owner)
        self.url = reverse("project-list")
        self.client = APIClient()

    def test_requires_workspace_query_param(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 400)

    def test_outsider_cannot_list(self):
        self.client.force_authenticate(self.outsider)
        response = self.client.get(self.url, {"workspace": self.workspace.id})
        self.assertEqual(response.status_code, 403)

    def test_member_can_list(self):
        self.client.force_authenticate(self.member)
        response = self.client.get(self.url, {"workspace": self.workspace.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_member_can_create_and_becomes_owner_member(self):
        self.client.force_authenticate(self.member)
        response = self.client.post(
            self.url, {"workspace": self.workspace.id, "name": "New Project"}, format="json"
        )
        self.assertEqual(response.status_code, 201)
        project = Project.objects.get(pk=response.data["id"])
        self.assertEqual(project.owner, self.member)
        self.assertTrue(
            ProjectMember.objects.filter(project=project, user=self.member, role="owner").exists()
        )

    def test_outsider_cannot_create(self):
        self.client.force_authenticate(self.outsider)
        response = self.client.post(
            self.url, {"workspace": self.workspace.id, "name": "Nope"}, format="json"
        )
        self.assertEqual(response.status_code, 403)


class ProjectDetailViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="downer", email="downer@example.com", password="pw")
        self.admin = User.objects.create_user(username="dadmin", email="dadmin@example.com", password="pw")
        self.member = User.objects.create_user(username="dmember", email="dmember@example.com", password="pw")
        self.outsider = User.objects.create_user(
            username="doutsider", email="doutsider@example.com", password="pw"
        )
        self.workspace = Workspace.objects.create(name="DWS", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role=Membership.Role.OWNER)
        Membership.objects.create(workspace=self.workspace, user=self.admin, role=Membership.Role.ADMIN)
        Membership.objects.create(workspace=self.workspace, user=self.member, role=Membership.Role.MEMBER)
        self.project = Project.objects.create(workspace=self.workspace, name="P", owner=self.member)
        self.url = reverse("project-detail", kwargs={"pk": self.project.pk})
        self.client = APIClient()

    def test_outsider_cannot_view(self):
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_workspace_member_can_view_even_if_not_project_owner(self):
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_project_owner_can_update(self):
        self.client.force_authenticate(self.member)
        response = self.client.patch(self.url, {"name": "Renamed"}, format="json")
        self.assertEqual(response.status_code, 200)

    def test_workspace_admin_can_update_even_if_not_project_owner(self):
        self.client.force_authenticate(self.admin)
        response = self.client.patch(self.url, {"name": "Renamed by admin"}, format="json")
        self.assertEqual(response.status_code, 200)

    def test_plain_member_cannot_update_someone_elses_project(self):
        other_member = User.objects.create_user(
            username="dmember2", email="dmember2@example.com", password="pw"
        )
        Membership.objects.create(workspace=self.workspace, user=other_member, role=Membership.Role.MEMBER)
        self.client.force_authenticate(other_member)
        response = self.client.patch(self.url, {"name": "Nope"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_project_owner_can_delete(self):
        self.client.force_authenticate(self.member)
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, 204)


class LabelViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="lowner", email="lowner@example.com", password="pw")
        self.member = User.objects.create_user(username="lmember", email="lmember@example.com", password="pw")
        self.outsider = User.objects.create_user(
            username="loutsider", email="loutsider@example.com", password="pw"
        )
        self.workspace = Workspace.objects.create(name="LWS", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role=Membership.Role.OWNER)
        Membership.objects.create(workspace=self.workspace, user=self.member, role=Membership.Role.MEMBER)
        self.label = Label.objects.create(workspace=self.workspace, name="bug", color="#f87171")
        self.list_url = reverse("label-list")

    def test_list_requires_membership(self):
        client = APIClient()
        client.force_authenticate(self.outsider)
        response = client.get(self.list_url, {"workspace": self.workspace.id})
        self.assertEqual(response.status_code, 403)

    def test_member_can_create_label(self):
        client = APIClient()
        client.force_authenticate(self.member)
        response = client.post(
            self.list_url,
            {"workspace": self.workspace.id, "name": "feature", "color": "#34d399"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)

    def test_member_cannot_modify_label_only_admin_can(self):
        detail_url = reverse("label-detail", kwargs={"pk": self.label.pk})
        client = APIClient()
        client.force_authenticate(self.member)
        response = client.patch(detail_url, {"name": "renamed"}, format="json")
        self.assertEqual(response.status_code, 403)

        client.force_authenticate(self.owner)
        response = client.patch(detail_url, {"name": "renamed"}, format="json")
        self.assertEqual(response.status_code, 200)


class NoteViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="nowner", email="nowner@example.com", password="pw")
        self.author = User.objects.create_user(username="nauthor", email="nauthor@example.com", password="pw")
        self.member = User.objects.create_user(username="nmember", email="nmember@example.com", password="pw")
        self.workspace = Workspace.objects.create(name="NWS", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role=Membership.Role.OWNER)
        Membership.objects.create(workspace=self.workspace, user=self.author, role=Membership.Role.MEMBER)
        Membership.objects.create(workspace=self.workspace, user=self.member, role=Membership.Role.MEMBER)
        self.project = Project.objects.create(workspace=self.workspace, name="P", owner=self.owner)
        self.note = Note.objects.create(project=self.project, title="N", body="body", author=self.author)
        self.list_url = reverse("project-notes", kwargs={"pk": self.project.pk})
        self.detail_url = reverse("note-detail", kwargs={"pk": self.note.pk})

    def test_member_can_create_a_note(self):
        client = APIClient()
        client.force_authenticate(self.member)
        response = client.post(self.list_url, {"title": "Another", "body": "..."}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["author"]["username"], "nmember")

    def test_other_member_cannot_edit_someone_elses_note(self):
        client = APIClient()
        client.force_authenticate(self.member)
        response = client.patch(self.detail_url, {"title": "Hijacked"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_author_can_edit_own_note(self):
        client = APIClient()
        client.force_authenticate(self.author)
        response = client.patch(self.detail_url, {"title": "Updated"}, format="json")
        self.assertEqual(response.status_code, 200)

    def test_admin_can_edit_someone_elses_note(self):
        client = APIClient()
        client.force_authenticate(self.owner)
        response = client.patch(self.detail_url, {"title": "Updated by owner"}, format="json")
        self.assertEqual(response.status_code, 200)
