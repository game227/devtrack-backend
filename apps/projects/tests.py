from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.workspaces.models import Membership, Workspace

from .models import Label, Note, Project, ProjectFavorite, ProjectMember

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


class ProjectMemberSpecialtyTests(TestCase):
    def setUp(self):
        from rest_framework.test import APIClient

        self.owner = User.objects.create_user(username="spowner", email="spowner@example.com", password="pw")
        self.dev = User.objects.create_user(username="spdev", email="spdev@example.com", password="pw")
        self.outsider = User.objects.create_user(username="spout", email="spout@example.com", password="pw")
        self.workspace = Workspace.objects.create(name="SPWS", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role=Membership.Role.OWNER)
        Membership.objects.create(workspace=self.workspace, user=self.dev, role=Membership.Role.MEMBER)
        self.project = Project.objects.create(workspace=self.workspace, name="P", owner=self.owner)
        ProjectMember.objects.create(project=self.project, user=self.owner, role="owner")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.list_url = reverse("project-members", kwargs={"pk": self.project.pk})

    def detail_url(self, user):
        return reverse("project-member-detail", kwargs={"pk": self.project.pk, "user_id": user.pk})

    def test_each_specialty_can_be_assigned_when_adding_a_member(self):
        for value in ("frontend", "backend", "debugger", "designer"):
            user = User.objects.create_user(username=f"sp_{value}", email=f"sp_{value}@example.com", password="pw")
            Membership.objects.create(workspace=self.workspace, user=user, role=Membership.Role.MEMBER)
            response = self.client.post(self.list_url, {"username": user.username, "specialty": value}, format="json")
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.data["specialty"], value)

    def test_specialty_is_optional_and_unknown_values_are_rejected(self):
        ok = self.client.post(self.list_url, {"username": "spdev"}, format="json")
        self.assertEqual((ok.status_code, ok.data["specialty"]), (201, ""))
        other = User.objects.create_user(username="spx", email="spx@example.com", password="pw")
        Membership.objects.create(workspace=self.workspace, user=other, role=Membership.Role.MEMBER)
        bad = self.client.post(self.list_url, {"username": "spx", "specialty": "wizard"}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertFalse(ProjectMember.objects.filter(user=other).exists())

    def test_specialty_can_be_changed_and_cleared(self):
        ProjectMember.objects.create(project=self.project, user=self.dev, role="member", specialty="backend")
        changed = self.client.patch(self.detail_url(self.dev), {"specialty": "designer"}, format="json")
        self.assertEqual((changed.status_code, changed.data["specialty"]), (200, "designer"))
        cleared = self.client.patch(self.detail_url(self.dev), {"specialty": ""}, format="json")
        self.assertEqual(cleared.data["specialty"], "")
        self.assertEqual(self.client.patch(self.detail_url(self.dev), {"specialty": "nope"}, format="json").status_code, 400)

    def test_members_list_exposes_specialty_and_only_managers_can_change_it(self):
        ProjectMember.objects.create(project=self.project, user=self.dev, role="member", specialty="debugger")
        listing = self.client.get(self.list_url)
        self.assertIn("debugger", [m["specialty"] for m in listing.data["results"]])

        self.client.force_authenticate(self.dev)  # a plain member
        self.assertEqual(self.client.patch(self.detail_url(self.dev), {"specialty": "frontend"}, format="json").status_code, 403)
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.patch(self.detail_url(self.dev), {"specialty": "frontend"}, format="json").status_code, 403)


class ProjectDateTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        from apps.workspaces.models import Membership, Workspace

        self.owner = get_user_model().objects.create_user(username="pd", email="pd@example.com", password="pw")
        self.workspace = Workspace.objects.create(name="PD", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role="owner")
        self.project = Project.objects.create(workspace=self.workspace, name="P", owner=self.owner)
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.url = reverse("project-detail", args=[self.project.id])

    def test_target_cannot_come_before_start(self):
        self.assertEqual(self.client.patch(self.url, {"start_date": "2026-12-10", "target_date": "2026-12-01"}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(self.url, {"start_date": "2026-12-01", "target_date": "2026-12-10"}, format="json").status_code, 200)
        # A partial update is compared with the stored other date.
        response = self.client.patch(self.url, {"target_date": "2026-11-20"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("target_date", response.data)
        self.assertEqual(self.client.patch(self.url, {"start_date": None, "target_date": None}, format="json").status_code, 200)


class ProjectCountTests(TestCase):
    def test_list_rows_carry_issue_counts(self):
        from apps.issues.models import Issue

        user = get_user_model().objects.create_user(username="pc", email="pc@example.com", password="pw")
        workspace = Workspace.objects.create(name="PC", owner=user)
        Membership.objects.create(workspace=workspace, user=user, role="owner")
        project = Project.objects.create(workspace=workspace, name="P", owner=user)
        Issue.objects.create(project=project, title="a", reporter=user, status="done")
        Issue.objects.create(project=project, title="b", reporter=user)
        client = APIClient()
        client.force_authenticate(user)
        row = client.get(reverse("project-list"), {"workspace": workspace.id}).data["results"][0]
        self.assertEqual((row["issue_count"], row["done_count"]), (2, 1))
        detail = client.get(reverse("project-detail", args=[project.id])).data
        self.assertEqual((detail["issue_count"], detail["done_count"]), (2, 1))


class ProjectFavoriteTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="fowner", email="fowner@example.com", password="pw")
        self.member = User.objects.create_user(username="fmember", email="fmember@example.com", password="pw")
        self.outsider = User.objects.create_user(username="foutsider", email="foutsider@example.com", password="pw")
        self.workspace = Workspace.objects.create(name="FWS", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role=Membership.Role.OWNER)
        Membership.objects.create(workspace=self.workspace, user=self.member, role=Membership.Role.MEMBER)
        self.project = Project.objects.create(workspace=self.workspace, name="Starred", owner=self.owner)
        self.url = reverse("project-favorite", args=[self.project.id])
        self.client = APIClient()

    def listed(self, user):
        self.client.force_authenticate(user)
        response = self.client.get(reverse("project-list"), {"workspace": self.workspace.id})
        return {row["id"]: row["is_favorite"] for row in response.data["results"]}

    def test_member_stars_and_unstars_and_it_is_personal(self):
        self.client.force_authenticate(self.member)
        self.assertEqual(self.client.put(self.url).data, {"is_favorite": True})
        # Starring twice is harmless.
        self.assertEqual(self.client.put(self.url).status_code, 200)
        self.assertEqual(ProjectFavorite.objects.filter(user=self.member).count(), 1)
        self.assertEqual(self.listed(self.member), {self.project.id: True})
        # The owner's view of the same project is unaffected.
        self.assertEqual(self.listed(self.owner), {self.project.id: False})
        self.client.force_authenticate(self.member)
        detail = self.client.get(reverse("project-detail", args=[self.project.id]))
        self.assertTrue(detail.data["is_favorite"])
        self.assertEqual(self.client.delete(self.url).data, {"is_favorite": False})
        self.assertEqual(self.client.delete(self.url).status_code, 200)
        self.assertEqual(self.listed(self.member), {self.project.id: False})

    def test_outsider_cannot_star(self):
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.put(self.url).status_code, 403)
        self.assertFalse(ProjectFavorite.objects.exists())

    def test_anonymous_cannot_star(self):
        self.assertEqual(self.client.put(self.url).status_code, 401)


class ProjectWeeklyDoneTests(TestCase):
    def test_lists_issues_finished_per_week_oldest_first(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.issues.models import Issue

        owner = User.objects.create_user(username="wowner", email="wowner@example.com", password="pw")
        workspace = Workspace.objects.create(name="WWS", owner=owner)
        Membership.objects.create(workspace=workspace, user=owner, role=Membership.Role.OWNER)
        project = Project.objects.create(workspace=workspace, name="Throughput", owner=owner)
        now = timezone.now()
        for number, (status, days_ago) in enumerate(
            [("done", 1), ("done", 2), ("done", 10), ("done", 60), ("todo", None)], start=1
        ):
            Issue.objects.create(
                project=project,
                number=number,
                title=f"Issue {number}",
                reporter=owner,
                status=status,
                completed_at=now - timedelta(days=days_ago) if days_ago else None,
            )
        client = APIClient()
        client.force_authenticate(owner)
        row = client.get(reverse("project-list"), {"workspace": workspace.id}).data["results"][0]
        # Eight weeks, this week last: two this week, one the week before, the 60-day-old one is out of range.
        self.assertEqual(row["weekly_done"], [0, 0, 0, 0, 0, 0, 1, 2])
        detail = client.get(reverse("project-detail", args=[project.id])).data
        self.assertIsNone(detail["weekly_done"])
