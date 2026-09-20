from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.workspaces.models import Membership, Workspace

from .models import Team, TeamMembership

User = get_user_model()


class TeamListCreateViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="towner", email="towner@example.com", password="pw")
        self.admin = User.objects.create_user(username="tadmin", email="tadmin@example.com", password="pw")
        self.member = User.objects.create_user(username="tmember", email="tmember@example.com", password="pw")
        self.outsider = User.objects.create_user(
            username="toutsider", email="toutsider@example.com", password="pw"
        )
        self.workspace = Workspace.objects.create(name="TWS", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role=Membership.Role.OWNER)
        Membership.objects.create(workspace=self.workspace, user=self.admin, role=Membership.Role.ADMIN)
        Membership.objects.create(workspace=self.workspace, user=self.member, role=Membership.Role.MEMBER)
        self.url = reverse("team-list")
        self.client = APIClient()

    def test_requires_workspace_param(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 400)

    def test_outsider_cannot_list(self):
        self.client.force_authenticate(self.outsider)
        response = self.client.get(self.url, {"workspace": self.workspace.id})
        self.assertEqual(response.status_code, 403)

    def test_plain_member_cannot_create_a_team(self):
        self.client.force_authenticate(self.member)
        response = self.client.post(
            self.url, {"workspace": self.workspace.id, "name": "Core"}, format="json"
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_can_create_a_team_and_joins_it(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            self.url, {"workspace": self.workspace.id, "name": "Core"}, format="json"
        )
        self.assertEqual(response.status_code, 201)
        team = Team.objects.get(pk=response.data["id"])
        self.assertTrue(TeamMembership.objects.filter(team=team, user=self.admin).exists())

    def test_member_can_list_teams(self):
        Team.objects.create(workspace=self.workspace, name="Existing")
        self.client.force_authenticate(self.member)
        response = self.client.get(self.url, {"workspace": self.workspace.id})
        self.assertEqual(response.data["count"], 1)


class TeamDetailAndMembersViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="tdowner", email="tdowner@example.com", password="pw")
        self.member = User.objects.create_user(username="tdmember", email="tdmember@example.com", password="pw")
        self.newcomer = User.objects.create_user(
            username="tdnewcomer", email="tdnewcomer@example.com", password="pw"
        )
        self.workspace = Workspace.objects.create(name="TDWS", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role=Membership.Role.OWNER)
        Membership.objects.create(workspace=self.workspace, user=self.member, role=Membership.Role.MEMBER)
        self.team = Team.objects.create(workspace=self.workspace, name="Core")
        TeamMembership.objects.create(team=self.team, user=self.owner)
        self.detail_url = reverse("team-detail", kwargs={"pk": self.team.pk})
        self.members_url = reverse("team-members", kwargs={"pk": self.team.pk})
        self.client = APIClient()

    def test_member_can_view_team_but_not_rename_it(self):
        self.client.force_authenticate(self.member)
        self.assertEqual(self.client.get(self.detail_url).status_code, 200)
        response = self.client.patch(self.detail_url, {"name": "Renamed"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_owner_can_rename_and_delete_team(self):
        self.client.force_authenticate(self.owner)
        response = self.client.patch(self.detail_url, {"name": "Renamed"}, format="json")
        self.assertEqual(response.status_code, 200)
        response = self.client.delete(self.detail_url)
        self.assertEqual(response.status_code, 204)

    def test_member_cannot_add_team_members(self):
        self.client.force_authenticate(self.member)
        response = self.client.post(self.members_url, {"username": "tdnewcomer"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_owner_can_add_and_remove_team_members(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(self.members_url, {"username": "tdnewcomer"}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(TeamMembership.objects.filter(team=self.team, user=self.newcomer).exists())

        member_detail_url = reverse(
            "team-member-detail", kwargs={"pk": self.team.pk, "user_id": self.newcomer.id}
        )
        response = self.client.delete(member_detail_url)
        self.assertEqual(response.status_code, 204)
        self.assertFalse(TeamMembership.objects.filter(team=self.team, user=self.newcomer).exists())
