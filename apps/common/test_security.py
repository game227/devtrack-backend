"""Cross-tenant authorization tests.

Every case here used to succeed (found by probing the API from the outside): a user could move their
own project/issue/label/cycle/milestone/team into someone else's workspace, point issues at people,
labels and cycles from other workspaces, add non-members to projects and teams, and keep editing things
after being removed from a workspace. Each test pins the fixed behaviour, with a positive control so
a test can never pass just because everything is rejected.
"""

import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.comments.models import Comment
from apps.cycles.models import Cycle
from apps.issues.models import Issue
from apps.milestones.models import Milestone
from apps.notifications.models import Notification
from apps.projects.models import Label, Project
from apps.teams.models import Team
from apps.workspaces.models import Membership, Workspace

User = get_user_model()


def make_user(name):
    return User.objects.create_user(username=name, email=f"{name}@example.com", password="pw-Str0ng-xyz")


class TwoWorkspaces(TestCase):
    """Alice owns workspace A; Bob owns workspace B; Carol belongs to neither."""

    def setUp(self):
        self.alice, self.bob, self.carol = make_user("alice"), make_user("bob"), make_user("carol")
        self.ws_a = Workspace.objects.create(name="A", owner=self.alice)
        self.ws_b = Workspace.objects.create(name="B", owner=self.bob)
        Membership.objects.create(workspace=self.ws_a, user=self.alice, role=Membership.Role.OWNER)
        Membership.objects.create(workspace=self.ws_b, user=self.bob, role=Membership.Role.OWNER)
        self.proj_a = Project.objects.create(workspace=self.ws_a, name="PA", owner=self.alice)
        self.proj_b = Project.objects.create(workspace=self.ws_b, name="PB", owner=self.bob)
        self.team_a = Team.objects.create(workspace=self.ws_a, name="TA")
        self.team_b = Team.objects.create(workspace=self.ws_b, name="TB")
        self.label_a = Label.objects.create(workspace=self.ws_a, name="la")
        self.label_b = Label.objects.create(workspace=self.ws_b, name="lb")
        span = dict(start_date=datetime.date(2026, 1, 1), end_date=datetime.date(2026, 1, 9))
        self.cycle_a = Cycle.objects.create(project=self.proj_a, name="ca", **span)
        self.cycle_b = Cycle.objects.create(project=self.proj_b, name="cb", **span)
        self.ms_a = Milestone.objects.create(project=self.proj_a, name="ma")
        self.ms_b = Milestone.objects.create(project=self.proj_b, name="mb")
        self.issue = Issue.objects.create(project=self.proj_a, title="mine", reporter=self.alice)
        self.client = APIClient()
        self.client.force_authenticate(self.alice)

    def patch(self, url, data):
        return self.client.patch(url, data, format="json")


class ParentsAreImmutableTests(TwoWorkspaces):
    def test_an_issue_cannot_be_moved_to_another_workspaces_project(self):
        self.patch(f"/api/v1/issues/{self.issue.id}/", {"project": self.proj_b.id})
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.project_id, self.proj_a.id)

    def test_a_project_cannot_be_moved_to_another_workspace(self):
        self.patch(f"/api/v1/projects/{self.proj_a.id}/", {"workspace": self.ws_b.id})
        self.proj_a.refresh_from_db()
        self.assertEqual(self.proj_a.workspace_id, self.ws_a.id)

    def test_a_label_cannot_be_moved_to_another_workspace(self):
        self.patch(f"/api/v1/labels/{self.label_a.id}/", {"workspace": self.ws_b.id})
        self.label_a.refresh_from_db()
        self.assertEqual(self.label_a.workspace_id, self.ws_a.id)

    def test_a_cycle_and_a_milestone_cannot_be_moved_to_another_project(self):
        self.patch(f"/api/v1/cycles/{self.cycle_a.id}/", {"project": self.proj_b.id})
        self.patch(f"/api/v1/milestones/{self.ms_a.id}/", {"project": self.proj_b.id})
        self.cycle_a.refresh_from_db()
        self.ms_a.refresh_from_db()
        self.assertEqual((self.cycle_a.project_id, self.ms_a.project_id), (self.proj_a.id, self.proj_a.id))

    def test_a_team_cannot_be_moved_to_another_workspace(self):
        self.patch(f"/api/v1/teams/{self.team_a.id}/", {"workspace": self.ws_b.id})
        self.team_a.refresh_from_db()
        self.assertEqual(self.team_a.workspace_id, self.ws_a.id)


class RelatedObjectsMustShareTheWorkspaceTests(TwoWorkspaces):
    def setUp(self):
        super().setUp()
        self.teammate = make_user("teammate")
        Membership.objects.create(workspace=self.ws_a, user=self.teammate, role=Membership.Role.MEMBER)
        self.url = f"/api/v1/issues/{self.issue.id}/"

    def test_an_issue_can_be_assigned_to_a_workspace_member(self):  # positive control
        response = self.patch(self.url, {"assignee_id": self.teammate.id})
        self.assertEqual((response.status_code, response.data["assignee"]["username"]), (200, "teammate"))

    def test_an_issue_cannot_be_assigned_to_someone_outside_the_workspace(self):
        for outsider in (self.bob, self.carol):
            response = self.patch(self.url, {"assignee_id": outsider.id})
            self.assertEqual(response.status_code, 400, outsider.username)
        self.issue.refresh_from_db()
        self.assertIsNone(self.issue.assignee_id)

    def test_a_deactivated_user_cannot_be_assigned(self):
        self.teammate.is_active = False
        self.teammate.save()
        self.assertEqual(self.patch(self.url, {"assignee_id": self.teammate.id}).status_code, 400)

    def test_labels_cycles_and_milestones_of_the_same_project_are_accepted(self):  # positive control
        response = self.patch(
            self.url, {"label_ids": [self.label_a.id], "cycle": self.cycle_a.id, "milestone": self.ms_a.id}
        )
        self.assertEqual(response.status_code, 200, response.data)

    def test_foreign_labels_cycles_and_milestones_are_rejected(self):
        for payload in (
            {"label_ids": [self.label_b.id]},
            {"cycle": self.cycle_b.id},
            {"milestone": self.ms_b.id},
        ):
            self.assertEqual(self.patch(self.url, payload).status_code, 400, payload)
        self.issue.refresh_from_db()
        self.assertEqual((self.issue.cycle_id, self.issue.milestone_id, self.issue.labels.count()), (None, None, 0))

    def test_a_label_scoped_to_another_project_of_the_workspace_is_rejected(self):
        other_project = Project.objects.create(workspace=self.ws_a, name="Other", owner=self.alice)
        scoped = Label.objects.create(workspace=self.ws_a, project=other_project, name="scoped")
        self.assertEqual(self.patch(self.url, {"label_ids": [scoped.id]}).status_code, 400)

    def test_creating_an_issue_applies_the_same_rules(self):
        base = {"project": self.proj_a.id, "title": "new"}
        self.assertEqual(self.client.post("/api/v1/issues/", {**base, "assignee_id": self.bob.id}, format="json").status_code, 400)
        self.assertEqual(self.client.post("/api/v1/issues/", {**base, "label_ids": [self.label_b.id]}, format="json").status_code, 400)
        ok = self.client.post("/api/v1/issues/", {**base, "assignee_id": self.teammate.id}, format="json")
        self.assertEqual(ok.status_code, 201, ok.data)
        self.assertEqual(Issue.objects.filter(title="new").count(), 1)

    def test_creating_in_a_foreign_project_is_forbidden(self):
        response = self.client.post("/api/v1/issues/", {"project": self.proj_b.id, "title": "x"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_a_label_cannot_be_created_for_a_project_of_another_workspace(self):
        response = self.client.post(
            "/api/v1/labels/", {"workspace": self.ws_a.id, "project": self.proj_b.id, "name": "x"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        ok = self.client.post(
            "/api/v1/labels/", {"workspace": self.ws_a.id, "project": self.proj_a.id, "name": "x"}, format="json"
        )
        self.assertEqual(ok.status_code, 201, ok.data)

    def test_a_project_can_only_use_a_team_of_its_own_workspace(self):
        self.assertEqual(self.patch(f"/api/v1/projects/{self.proj_a.id}/", {"team": self.team_b.id}).status_code, 400)
        ok = self.patch(f"/api/v1/projects/{self.proj_a.id}/", {"team": self.team_a.id})
        self.assertEqual(ok.status_code, 200, ok.data)
        created = self.client.post(
            "/api/v1/projects/", {"workspace": self.ws_a.id, "name": "n", "team": self.team_b.id}, format="json"
        )
        self.assertEqual(created.status_code, 400)

    def test_a_team_name_must_stay_unique_in_its_workspace(self):
        Team.objects.create(workspace=self.ws_a, name="Dup")
        response = self.client.post("/api/v1/teams/", {"workspace": self.ws_a.id, "name": "Dup"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.patch(f"/api/v1/teams/{self.team_a.id}/", {"name": "Dup"}).status_code, 400)
        self.assertEqual(self.patch(f"/api/v1/teams/{self.team_a.id}/", {"name": "TA"}).status_code, 200)


class OnlyWorkspaceMembersCanJoinProjectsAndTeamsTests(TwoWorkspaces):
    def setUp(self):
        super().setUp()
        self.teammate = make_user("teammate")
        Membership.objects.create(workspace=self.ws_a, user=self.teammate, role=Membership.Role.MEMBER)

    def test_project_members(self):
        url = f"/api/v1/projects/{self.proj_a.id}/members/"
        for outsider in ("bob", "carol", "no-such-user"):
            self.assertEqual(self.client.post(url, {"username": outsider}, format="json").status_code, 400, outsider)
        self.assertEqual(self.client.post(url, {"username": "teammate"}, format="json").status_code, 201)

    def test_team_members(self):
        url = f"/api/v1/teams/{self.team_a.id}/members/"
        for outsider in ("bob", "carol"):
            self.assertEqual(self.client.post(url, {"username": outsider}, format="json").status_code, 400, outsider)
        self.assertEqual(self.client.post(url, {"username": "teammate"}, format="json").status_code, 201)

    def test_unknown_and_non_member_usernames_get_the_same_answer(self):
        url = f"/api/v1/projects/{self.proj_a.id}/members/"
        unknown = self.client.post(url, {"username": "no-such-user"}, format="json").data
        existing = self.client.post(url, {"username": "carol"}, format="json").data
        self.assertEqual(unknown, existing)  # cannot be used to find out which usernames exist

    def test_a_deactivated_account_cannot_be_added_to_a_workspace(self):
        self.carol.is_active = False
        self.carol.save()
        response = self.client.post(f"/api/v1/workspaces/{self.ws_a.id}/members/", {"username": "carol"}, format="json")
        self.assertEqual(response.status_code, 400)


class NotificationsStayInsideTheWorkspaceTests(TwoWorkspaces):
    def test_mentioning_someone_outside_the_workspace_notifies_nobody(self):
        self.client.post(f"/api/v1/issues/{self.issue.id}/comments/", {"body": "hi @carol and @bob"}, format="json")
        self.assertFalse(Notification.objects.filter(recipient__in=[self.carol, self.bob]).exists())

    def test_mentioning_a_member_still_works(self):
        mate = make_user("mate")
        Membership.objects.create(workspace=self.ws_a, user=mate, role=Membership.Role.MEMBER)
        self.client.post(f"/api/v1/issues/{self.issue.id}/comments/", {"body": "ping @mate"}, format="json")
        self.assertTrue(Notification.objects.filter(recipient=mate, verb="mentioned").exists())

    def test_someone_removed_from_the_workspace_stops_hearing_about_it(self):
        dev = make_user("dev")
        membership = Membership.objects.create(workspace=self.ws_a, user=dev, role=Membership.Role.MEMBER)
        self.issue.assignee = dev
        self.issue.save()
        membership.delete()
        Notification.objects.all().delete()
        Comment.objects.create(author=self.alice, body="secret plans", content_object=self.issue)
        self.assertFalse(Notification.objects.filter(recipient=dev).exists())


class FormerMembersLoseTheirRightsTests(TwoWorkspaces):
    """Being removed from a workspace must end the rights that came from having created something in it."""

    def setUp(self):
        super().setUp()
        self.dev = make_user("dev")
        self.membership = Membership.objects.create(workspace=self.ws_a, user=self.dev, role=Membership.Role.MEMBER)
        self.dev_issue = Issue.objects.create(project=self.proj_a, title="dev's", reporter=self.dev)
        self.dev_project = Project.objects.create(workspace=self.ws_a, name="dev's project", owner=self.dev)
        self.dev_client = APIClient()
        self.dev_client.force_authenticate(self.dev)

    def test_while_a_member_the_creator_can_edit_and_manage(self):  # positive control
        self.assertEqual(self.dev_client.patch(f"/api/v1/issues/{self.dev_issue.id}/", {"title": "x"}, format="json").status_code, 200)
        self.assertEqual(self.dev_client.patch(f"/api/v1/projects/{self.dev_project.id}/", {"name": "x"}, format="json").status_code, 200)

    def test_after_removal_the_creator_can_no_longer_touch_it(self):
        self.membership.delete()
        issue_url, project_url = f"/api/v1/issues/{self.dev_issue.id}/", f"/api/v1/projects/{self.dev_project.id}/"
        self.assertEqual(self.dev_client.patch(issue_url, {"title": "x"}, format="json").status_code, 403)
        self.assertEqual(self.dev_client.delete(issue_url).status_code, 403)
        self.assertEqual(self.dev_client.get(issue_url).status_code, 403)
        self.assertEqual(self.dev_client.patch(project_url, {"name": "x"}, format="json").status_code, 403)
        self.assertEqual(self.dev_client.delete(project_url).status_code, 403)
        self.assertEqual(self.dev_client.post(f"/api/v1/projects/{self.dev_project.id}/members/", {"username": "carol"}, format="json").status_code, 403)
        self.dev_issue.refresh_from_db()
        self.assertEqual(self.dev_issue.title, "dev's")


class MalformedInputIsA400NotA500Tests(TwoWorkspaces):
    def setUp(self):
        super().setUp()
        self.client = APIClient(raise_request_exception=False)
        self.client.force_authenticate(self.alice)

    def test_garbage_ids_in_query_strings(self):
        for url in (
            "/api/v1/issues/?project=abc",
            "/api/v1/issues/?workspace=abc",
            "/api/v1/issues/?workspace=99999999999999999999999",
            "/api/v1/labels/?workspace=abc",
            f"/api/v1/labels/?workspace={self.ws_a.id}&project=abc",
            "/api/v1/projects/?workspace=abc",
            "/api/v1/teams/?workspace=abc",
            "/api/v1/cycles/?project=abc",
            "/api/v1/milestones/?project=abc",
            "/api/v1/activities/?project=abc",
            "/api/v1/dashboard/?workspace=abc",
            "/api/v1/search/?workspace=abc&q=x",
        ):
            self.assertEqual(self.client.get(url).status_code, 400, url)

    def test_garbage_ids_and_shapes_in_request_bodies(self):
        for url in ("/api/v1/issues/", "/api/v1/cycles/", "/api/v1/milestones/"):
            for body in ({"project": "abc"}, {"project": [1]}, {"project": None}, [1, 2], "text"):
                self.assertEqual(self.client.post(url, body, format="json").status_code, 400, (url, body))
        for url in ("/api/v1/projects/", "/api/v1/labels/", "/api/v1/teams/"):
            for body in ({"workspace": "abc"}, {"workspace": {"a": 1}}, [1, 2]):
                self.assertEqual(self.client.post(url, body, format="json").status_code, 400, (url, body))

    def test_an_assignee_filter_that_is_not_a_number_matches_nothing(self):
        response = self.client.get(f"/api/v1/issues/?project={self.proj_a.id}&assignee=abc")
        self.assertEqual((response.status_code, response.data["count"]), (200, 0))


class ApiResponseHeadersTests(TestCase):
    def test_api_responses_are_not_cacheable_and_cannot_render_content(self):
        response = self.client.get("/api/v1/health/")
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertIn("default-src 'none'", response["Content-Security-Policy"])

    def test_other_paths_are_left_alone(self):
        response = self.client.get("/definitely-not-here/")
        self.assertNotIn("no-store", response.get("Cache-Control", ""))
