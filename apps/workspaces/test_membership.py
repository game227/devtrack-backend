"""Managing who belongs to a workspace: the permission table in membership.py, cell by cell."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.activities.models import Activity
from apps.issues.models import Issue
from apps.projects.models import Project, ProjectMember
from apps.teams.models import Team, TeamMembership

from .models import Membership, Workspace

User = get_user_model()


class MembershipManagementTests(TestCase):
    def setUp(self):
        mk = lambda name: User.objects.create_user(username=name, email=f"{name}@example.com", password="pw")  # noqa: E731
        self.owner, self.admin, self.admin2, self.member, self.member2 = (mk(n) for n in ("mowner", "madmin", "madmin2", "mmember", "mmember2"))
        self.workspace = Workspace.objects.create(name="Team WS", owner=self.owner)
        for user, role in ((self.owner, "owner"), (self.admin, "admin"), (self.admin2, "admin"), (self.member, "member"), (self.member2, "member")):
            Membership.objects.create(workspace=self.workspace, user=user, role=role)

    def as_(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def member_url(self, user):
        return reverse("workspace-member-detail", kwargs={"pk": self.workspace.pk, "user_id": user.id})

    def role_of(self, user):
        return Membership.objects.get(workspace=self.workspace, user=user).role

    def last_activity(self):
        return Activity.objects.filter(workspace=self.workspace).latest("id")

    # --- roles ------------------------------------------------------------------------------
    def test_the_owner_promotes_and_demotes(self):
        response = self.as_(self.owner).patch(self.member_url(self.member), {"role": "admin"}, format="json")
        self.assertEqual((response.status_code, self.role_of(self.member)), (200, "admin"))
        activity = self.last_activity()
        self.assertEqual((activity.verb, activity.metadata["user"], activity.metadata["role"]), ("role_changed", "mmember", "admin"))
        self.as_(self.owner).patch(self.member_url(self.member), {"role": "member"}, format="json")
        self.assertEqual(self.role_of(self.member), "member")

    def test_nobody_else_changes_roles_and_the_owner_role_is_not_editable(self):
        self.assertEqual(self.as_(self.admin).patch(self.member_url(self.member), {"role": "admin"}, format="json").status_code, 403)
        self.assertEqual(self.as_(self.member).patch(self.member_url(self.member2), {"role": "admin"}, format="json").status_code, 403)
        self.assertEqual(self.as_(self.owner).patch(self.member_url(self.owner), {"role": "member"}, format="json").status_code, 400)
        for bad in ("owner", "god", "", None):
            self.assertEqual(self.as_(self.owner).patch(self.member_url(self.member), {"role": bad}, format="json").status_code, 400, bad)
        self.assertEqual(self.role_of(self.member), "member")

    # --- removing ---------------------------------------------------------------------------
    def test_who_may_remove_whom(self):
        self.assertEqual(self.as_(self.admin).delete(self.member_url(self.admin2)).status_code, 403)  # admins: members only
        self.assertEqual(self.as_(self.admin).delete(self.member_url(self.owner)).status_code, 400)
        self.assertEqual(self.as_(self.member).delete(self.member_url(self.member2)).status_code, 403)
        self.assertEqual(self.as_(self.admin).delete(self.member_url(self.admin)).status_code, 400)  # use leave
        self.assertEqual(self.as_(self.admin).delete(self.member_url(self.member)).status_code, 204)
        self.assertEqual(self.as_(self.owner).delete(self.member_url(self.admin2)).status_code, 204)
        self.assertEqual(Membership.objects.filter(workspace=self.workspace).count(), 3)

    def test_removal_cleans_up_projects_teams_and_open_assignments(self):
        project = Project.objects.create(workspace=self.workspace, name="P", owner=self.owner)
        ProjectMember.objects.create(project=project, user=self.member)
        team = Team.objects.create(workspace=self.workspace, name="T")
        TeamMembership.objects.create(team=team, user=self.member)
        open_issue = Issue.objects.create(project=project, title="open", reporter=self.owner, assignee=self.member)
        finished = Issue.objects.create(project=project, title="done", reporter=self.owner, assignee=self.member, status="done")
        other_workspace = Workspace.objects.create(name="Elsewhere", owner=self.member)
        Membership.objects.create(workspace=other_workspace, user=self.member, role="owner")
        elsewhere = Issue.objects.create(project=Project.objects.create(workspace=other_workspace, name="E", owner=self.member), title="mine elsewhere", reporter=self.member, assignee=self.member)

        self.as_(self.owner).delete(self.member_url(self.member))

        self.assertFalse(ProjectMember.objects.filter(user=self.member, project=project).exists())
        self.assertFalse(TeamMembership.objects.filter(user=self.member, team=team).exists())
        for issue in (open_issue, finished, elsewhere):
            issue.refresh_from_db()
        self.assertIsNone(open_issue.assignee_id)
        self.assertEqual(finished.assignee_id, self.member.id)  # history stays
        self.assertEqual(elsewhere.assignee_id, self.member.id)  # other workspaces are untouched
        activity = self.last_activity()
        self.assertEqual((activity.verb, activity.actor, activity.metadata), ("member_removed", self.owner, {"user": "mmember", "unassigned": 1}))

    # --- leaving ----------------------------------------------------------------------------
    def test_members_and_admins_can_leave_the_owner_cannot(self):
        leave = reverse("workspace-leave", kwargs={"pk": self.workspace.pk})
        self.assertEqual(self.as_(self.member).post(leave).status_code, 204)
        self.assertEqual(self.last_activity().verb, "member_left")
        self.assertEqual(self.as_(self.admin).post(leave).status_code, 204)
        self.assertEqual(self.as_(self.owner).post(leave).status_code, 400)
        self.assertEqual(self.as_(self.member).post(leave).status_code, 404)  # already gone

    # --- handing over -----------------------------------------------------------------------
    def test_the_owner_hands_the_workspace_over_and_stays_as_admin(self):
        url = reverse("workspace-transfer-ownership", kwargs={"pk": self.workspace.pk})
        self.assertEqual(self.as_(self.admin).post(url, {"user_id": self.member.id}, format="json").status_code, 403)
        self.assertEqual(self.as_(self.owner).post(url, {"user_id": self.owner.id}, format="json").status_code, 400)
        outsider = User.objects.create_user(username="mout", email="mout@example.com", password="pw")
        self.assertEqual(self.as_(self.owner).post(url, {"user_id": outsider.id}, format="json").status_code, 400)
        self.assertEqual(self.as_(self.owner).post(url, {"user_id": "abc"}, format="json").status_code, 400)

        response = self.as_(self.owner).post(url, {"user_id": self.member.id}, format="json")
        self.assertEqual(response.status_code, 200)
        self.workspace.refresh_from_db()
        self.assertEqual((self.workspace.owner, self.role_of(self.member), self.role_of(self.owner)), (self.member, "owner", "admin"))
        self.assertEqual(self.last_activity().verb, "ownership_transferred")
        leave = reverse("workspace-leave", kwargs={"pk": self.workspace.pk})
        self.assertEqual(self.as_(self.owner).post(leave).status_code, 204)  # no longer the owner: may leave

    def test_a_personal_workspace_cannot_change_hands(self):
        self.workspace.is_personal = True
        self.workspace.save()
        url = reverse("workspace-transfer-ownership", kwargs={"pk": self.workspace.pk})
        self.assertEqual(self.as_(self.owner).post(url, {"user_id": self.member.id}, format="json").status_code, 400)

    # --- inviting ---------------------------------------------------------------------------
    def test_admins_invite_members_only_the_owner_may_invite_admins(self):
        guest = User.objects.create_user(username="mguest", email="mguest@example.com", password="pw")
        url = reverse("workspace-members", kwargs={"pk": self.workspace.pk})
        self.assertEqual(self.as_(self.admin).post(url, {"username": "mguest", "role": "admin"}, format="json").status_code, 400)
        self.assertEqual(self.as_(self.owner).post(url, {"username": "mguest", "role": "admin"}, format="json").status_code, 201)
        invitation_id = self.as_(guest).get(reverse("my-invitations")).data["results"][0]["id"]
        self.as_(guest).post(reverse("invitation-accept", kwargs={"invitation_id": invitation_id}))
        activity = self.last_activity()
        self.assertEqual((activity.verb, activity.actor, activity.metadata["role"]), ("member_joined", guest, "admin"))
