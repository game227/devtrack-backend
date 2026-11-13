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

    def test_owner_invites_by_username_and_the_invitee_decides(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(self.members_url, {"username": "newcomer3", "role": "admin"}, format="json")
        self.assertEqual(response.status_code, 201)
        invitation_id = response.data["id"]
        # Not a member yet: the invitee cannot see the workspace until they accept.
        self.assertFalse(Membership.objects.filter(workspace=self.workspace, user=self.newcomer).exists())
        self.assertEqual(self.client.post(self.members_url, {"username": "newcomer3"}, format="json").status_code, 400)

        invitee = APIClient()
        invitee.force_authenticate(self.newcomer)
        self.assertEqual(invitee.get(reverse("workspace-detail", kwargs={"pk": self.workspace.pk})).status_code, 403)
        mine = invitee.get(reverse("my-invitations")).data["results"]
        self.assertEqual([(i["workspace"]["name"], i["role"], i["invited_by"]["username"]) for i in mine], [("WS3", "admin", "owner3")])

        accepted = invitee.post(reverse("invitation-accept", kwargs={"invitation_id": invitation_id}))
        self.assertEqual(accepted.status_code, 201)
        self.assertEqual(Membership.objects.get(workspace=self.workspace, user=self.newcomer).role, "admin")
        self.assertEqual(invitee.get(reverse("my-invitations")).data["count"], 0)

    def test_an_invitation_can_be_declined_and_only_by_its_invitee(self):
        self.client.force_authenticate(self.owner)
        invitation_id = self.client.post(self.members_url, {"username": "newcomer3"}, format="json").data["id"]
        stranger = APIClient()
        stranger.force_authenticate(self.member)
        self.assertEqual(stranger.post(reverse("invitation-accept", kwargs={"invitation_id": invitation_id})).status_code, 404)
        invitee = APIClient()
        invitee.force_authenticate(self.newcomer)
        self.assertEqual(invitee.post(reverse("invitation-decline", kwargs={"invitation_id": invitation_id})).status_code, 204)
        self.assertFalse(Membership.objects.filter(workspace=self.workspace, user=self.newcomer).exists())

    def test_admins_see_and_revoke_pending_invitations_members_do_not(self):
        self.client.force_authenticate(self.owner)
        invitation_id = self.client.post(self.members_url, {"username": "newcomer3"}, format="json").data["id"]
        url = reverse("workspace-invitations", kwargs={"pk": self.workspace.pk})
        self.assertEqual(self.client.get(url).data["count"], 1)
        member = APIClient()
        member.force_authenticate(self.member)
        self.assertEqual(member.get(url).status_code, 403)
        detail = reverse("workspace-invitation-detail", kwargs={"pk": self.workspace.pk, "invitation_id": invitation_id})
        self.assertEqual(member.delete(detail).status_code, 403)
        self.assertEqual(self.client.delete(detail).status_code, 204)
        invitee = APIClient()
        invitee.force_authenticate(self.newcomer)
        self.assertEqual(invitee.post(reverse("invitation-accept", kwargs={"invitation_id": invitation_id})).status_code, 404)

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


class InvitationValidityTests(TestCase):
    """An invitation is only as good as the admin who sent it, and only for a while."""

    def setUp(self):
        from rest_framework.test import APIClient

        from apps.notifications.models import Notification

        self.Notification = Notification
        self.owner = User.objects.create_user(username="vowner", email="vowner@example.com", password="pw")
        self.admin = User.objects.create_user(username="vadmin", email="vadmin@example.com", password="pw")
        self.guest = User.objects.create_user(username="vguest", email="vguest@example.com", password="pw")
        self.workspace = Workspace.objects.create(name="VWS", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role=Membership.Role.OWNER)
        self.admin_membership = Membership.objects.create(workspace=self.workspace, user=self.admin, role=Membership.Role.ADMIN)
        self.as_admin, self.as_guest, self.as_owner = APIClient(), APIClient(), APIClient()
        self.as_admin.force_authenticate(self.admin)
        self.as_guest.force_authenticate(self.guest)
        self.as_owner.force_authenticate(self.owner)
        members = reverse("workspace-members", kwargs={"pk": self.workspace.pk})
        response = self.as_admin.post(members, {"username": "vguest", "role": "admin"}, format="json")
        self.assertEqual(response.status_code, 201)
        self.invitation_id = response.data["id"]
        self.members_url = members

    def accept(self):
        return self.as_guest.post(reverse("invitation-accept", kwargs={"invitation_id": self.invitation_id}))

    def pending(self):
        return self.as_guest.get(reverse("my-invitations")).data["count"]

    def assert_dead(self):
        self.assertEqual(self.pending(), 0)
        self.assertEqual(self.accept().status_code, 404)
        self.assertFalse(Membership.objects.filter(workspace=self.workspace, user=self.guest).exists())

    def test_a_demoted_inviter_takes_their_offer_with_them(self):
        self.admin_membership.role = Membership.Role.MEMBER
        self.admin_membership.save()
        self.assert_dead()

    def test_a_removed_inviter_takes_their_offer_with_them(self):
        self.admin_membership.delete()
        self.assert_dead()

    def test_an_old_invitation_expires_and_can_be_sent_again(self):
        from datetime import timedelta

        from django.utils import timezone

        from .models import INVITATION_TTL, Invitation

        Invitation.objects.filter(pk=self.invitation_id).update(created_at=timezone.now() - INVITATION_TTL - timedelta(minutes=1))
        self.assertEqual(self.pending(), 0)
        again = self.as_owner.post(self.members_url, {"username": "vguest"}, format="json")
        self.assertEqual(again.status_code, 201)
        self.invitation_id = again.data["id"]
        self.assertEqual(self.accept().status_code, 201)

    def test_the_invitation_notification_goes_away_with_the_invitation(self):
        def notified():
            return self.Notification.objects.filter(recipient=self.guest, verb="workspace_invited").exists()

        self.assertTrue(notified())
        self.as_guest.post(reverse("invitation-decline", kwargs={"invitation_id": self.invitation_id}))
        self.assertFalse(notified())

        again = self.as_owner.post(self.members_url, {"username": "vguest"}, format="json").data["id"]
        self.assertTrue(notified())
        self.as_owner.delete(reverse("workspace-invitation-detail", kwargs={"pk": self.workspace.pk, "invitation_id": again}))
        self.assertFalse(notified())
