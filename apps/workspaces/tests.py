from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from .models import Membership, Workspace

User = get_user_model()


class WorkspaceSlugTests(TestCase):
    def test_slug_is_generated_from_name(self):
        owner = User.objects.create_user(username="owner", email="owner@example.com", password="pw")
        workspace = Workspace.objects.create(name="Acme Engineering", owner=owner)
        self.assertEqual(workspace.slug, "acme-engineering")

    def test_slug_collision_gets_a_unique_suffix(self):
        owner = User.objects.create_user(username="owner", email="owner@example.com", password="pw")
        first = Workspace.objects.create(name="Acme", owner=owner)
        second = Workspace.objects.create(name="Acme", owner=owner)
        self.assertEqual(first.slug, "acme")
        self.assertNotEqual(second.slug, "acme")
        self.assertTrue(second.slug.startswith("acme-"))


class WorkspaceListCreateViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", email="owner@example.com", password="pw")
        self.outsider = User.objects.create_user(
            username="outsider", email="outsider@example.com", password="pw"
        )
        self.workspace = Workspace.objects.create(name="WS", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role=Membership.Role.OWNER)
        self.url = reverse("workspace-list")
        self.client = APIClient()

    def test_list_only_returns_workspaces_the_user_is_a_member_of(self):
        # Every user also gets an auto-created personal workspace (see
        # apps.workspaces.signals.create_personal_workspace).
        self.client.force_authenticate(self.outsider)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertNotIn(self.workspace.id, [w["id"] for w in response.data["results"]])

        self.client.force_authenticate(self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.data["count"], 2)

    def test_create_makes_the_creator_the_owner_member(self):
        self.client.force_authenticate(self.outsider)
        response = self.client.post(self.url, {"name": "New Workspace"}, format="json")
        self.assertEqual(response.status_code, 201)
        workspace = Workspace.objects.get(pk=response.data["id"])
        self.assertEqual(workspace.owner, self.outsider)
        membership = Membership.objects.get(workspace=workspace, user=self.outsider)
        self.assertEqual(membership.role, Membership.Role.OWNER)

    def test_create_requires_authentication(self):
        response = self.client.post(self.url, {"name": "New Workspace"}, format="json")
        self.assertEqual(response.status_code, 401)


class WorkspaceDetailViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner2", email="owner2@example.com", password="pw")
        self.admin = User.objects.create_user(username="admin2", email="admin2@example.com", password="pw")
        self.member = User.objects.create_user(username="member2", email="member2@example.com", password="pw")
        self.outsider = User.objects.create_user(
            username="outsider2", email="outsider2@example.com", password="pw"
        )
        self.workspace = Workspace.objects.create(name="WS2", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role=Membership.Role.OWNER)
        Membership.objects.create(workspace=self.workspace, user=self.admin, role=Membership.Role.ADMIN)
        Membership.objects.create(workspace=self.workspace, user=self.member, role=Membership.Role.MEMBER)
        self.url = reverse("workspace-detail", kwargs={"pk": self.workspace.pk})
        self.client = APIClient()

    def test_outsider_cannot_view(self):
        self.client.force_authenticate(self.outsider)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_member_can_view(self):
        self.client.force_authenticate(self.member)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_member_cannot_update(self):
        self.client.force_authenticate(self.member)
        response = self.client.patch(self.url, {"name": "Renamed"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_admin_can_update(self):
        self.client.force_authenticate(self.admin)
        response = self.client.patch(self.url, {"name": "Renamed"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.workspace.refresh_from_db()
        self.assertEqual(self.workspace.name, "Renamed")

    def test_admin_cannot_delete(self):
        self.client.force_authenticate(self.admin)
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, 403)

    def test_owner_can_delete(self):
        self.client.force_authenticate(self.owner)
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Workspace.objects.filter(pk=self.workspace.pk).exists())


class WorkspaceMembersViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner3", email="owner3@example.com", password="pw")
        self.member = User.objects.create_user(username="member3", email="member3@example.com", password="pw")
        self.newcomer = User.objects.create_user(
            username="newcomer3", email="newcomer3@example.com", password="pw"
        )
        self.workspace = Workspace.objects.create(name="WS3", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role=Membership.Role.OWNER)
        Membership.objects.create(workspace=self.workspace, user=self.member, role=Membership.Role.MEMBER)
        self.members_url = reverse("workspace-members", kwargs={"pk": self.workspace.pk})
        self.client = APIClient()

    def test_member_can_list_but_not_add(self):
        self.client.force_authenticate(self.member)
        response = self.client.get(self.members_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)

        response = self.client.post(self.members_url, {"username": "newcomer3"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_owner_can_add_a_member_by_username(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(self.members_url, {"username": "newcomer3"}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            Membership.objects.filter(workspace=self.workspace, user=self.newcomer).exists()
        )

    def test_adding_an_existing_member_fails(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(self.members_url, {"username": "member3"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_adding_an_unknown_username_fails(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(self.members_url, {"username": "ghost"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_owner_cannot_be_removed(self):
        self.client.force_authenticate(self.owner)
        detail_url = reverse(
            "workspace-member-detail", kwargs={"pk": self.workspace.pk, "user_id": self.owner.id}
        )
        response = self.client.delete(detail_url)
        self.assertEqual(response.status_code, 400)

    def test_owner_can_remove_a_member(self):
        self.client.force_authenticate(self.owner)
        detail_url = reverse(
            "workspace-member-detail", kwargs={"pk": self.workspace.pk, "user_id": self.member.id}
        )
        response = self.client.delete(detail_url)
        self.assertEqual(response.status_code, 204)
        self.assertFalse(
            Membership.objects.filter(workspace=self.workspace, user=self.member).exists()
        )

    def test_member_cannot_remove_another_member(self):
        self.client.force_authenticate(self.member)
        detail_url = reverse(
            "workspace-member-detail", kwargs={"pk": self.workspace.pk, "user_id": self.owner.id}
        )
        response = self.client.delete(detail_url)
        self.assertEqual(response.status_code, 403)
