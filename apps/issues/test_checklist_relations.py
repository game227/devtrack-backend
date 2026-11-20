from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.live.models import WorkspaceClock
from apps.projects.models import Project
from apps.workspaces.models import Membership, Workspace

from .models import ChecklistItem, Issue, IssueRelation
from .serializers import MAX_CHECKLIST_ITEMS

User = get_user_model()


class Base(TestCase):
    def setUp(self):
        self.reporter = User.objects.create_user(username="c-rep", email="crep@example.com", password="pw")
        self.assignee = User.objects.create_user(username="c-ass", email="cass@example.com", password="pw")
        self.member = User.objects.create_user(username="c-mem", email="cmem@example.com", password="pw")
        self.outsider = User.objects.create_user(username="c-out", email="cout@example.com", password="pw")
        self.workspace = Workspace.objects.create(name="CW", owner=self.reporter)
        for user, role in [(self.reporter, "owner"), (self.assignee, "member"), (self.member, "member")]:
            Membership.objects.create(workspace=self.workspace, user=user, role=role)
        other_ws = Workspace.objects.create(name="Else", owner=self.outsider)
        Membership.objects.create(workspace=other_ws, user=self.outsider, role="owner")
        self.project = Project.objects.create(workspace=self.workspace, name="P", owner=self.reporter)
        self.project2 = Project.objects.create(workspace=self.workspace, name="P2", owner=self.reporter)
        self.issue = Issue.objects.create(project=self.project, title="Main", reporter=self.reporter, assignee=self.assignee)
        self.other = Issue.objects.create(project=self.project2, title="Other", reporter=self.member)
        self.foreign = Issue.objects.create(
            project=Project.objects.create(workspace=other_ws, name="X", owner=self.outsider), title="Foreign", reporter=self.outsider
        )
        self.client = APIClient()


class ChecklistTests(Base):
    def url(self):
        return reverse("issue-checklist", args=[self.issue.id])

    def test_reporter_and_assignee_manage_the_checklist(self):
        self.client.force_authenticate(self.reporter)
        first = self.client.post(self.url(), {"text": "  Write   tests "}, format="json")
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(first.data["text"], "Write tests")
        self.client.post(self.url(), {"text": "Ship"}, format="json")

        self.client.force_authenticate(self.assignee)
        item = reverse("checklist-item", args=[first.data["id"]])
        response = self.client.patch(item, {"done": True}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["done"])
        listed = self.client.get(self.url()).data
        self.assertEqual([(i["text"], i["done"]) for i in listed], [("Write tests", True), ("Ship", False)])
        self.assertEqual(self.client.delete(item).status_code, 204)
        self.assertEqual(ChecklistItem.objects.count(), 1)

    def test_other_members_read_but_cannot_change(self):
        item = ChecklistItem.objects.create(issue=self.issue, text="Step", position=1)
        self.client.force_authenticate(self.member)
        self.assertEqual(len(self.client.get(self.url()).data), 1)
        self.assertEqual(self.client.post(self.url(), {"text": "Mine"}, format="json").status_code, 403)
        self.assertEqual(self.client.patch(reverse("checklist-item", args=[item.id]), {"done": True}, format="json").status_code, 403)
        self.assertEqual(self.client.delete(reverse("checklist-item", args=[item.id])).status_code, 403)

    def test_outsiders_do_not_see_it(self):
        item = ChecklistItem.objects.create(issue=self.issue, text="Step", position=1)
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        self.assertEqual(self.client.patch(reverse("checklist-item", args=[item.id]), {"done": True}, format="json").status_code, 404)

    def test_text_is_required_and_the_list_is_bounded(self):
        self.client.force_authenticate(self.reporter)
        self.assertEqual(self.client.post(self.url(), {"text": "   "}, format="json").status_code, 400)
        ChecklistItem.objects.bulk_create(ChecklistItem(issue=self.issue, text=f"s{i}", position=i) for i in range(MAX_CHECKLIST_ITEMS))
        self.assertEqual(self.client.post(self.url(), {"text": "one more"}, format="json").status_code, 400)

    def test_changes_reach_live_updates(self):
        self.client.force_authenticate(self.reporter)
        WorkspaceClock.objects.filter(workspace=self.workspace).update(issues_at=None)
        self.client.post(self.url(), {"text": "Step"}, format="json")
        self.assertIsNotNone(WorkspaceClock.objects.get(workspace=self.workspace).issues_at)


class RelationTests(Base):
    def url(self, issue=None):
        return reverse("issue-relations", args=[(issue or self.issue).id])

    def test_a_link_shows_from_both_ends(self):
        self.client.force_authenticate(self.reporter)
        response = self.client.post(self.url(), {"kind": "blocks", "target_id": self.other.id}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["direction"], "out")
        self.assertEqual(response.data["other"]["title"], "Other")

        self.client.force_authenticate(self.member)
        seen_from_other = self.client.get(self.url(self.other)).data
        self.assertEqual(len(seen_from_other), 1)
        self.assertEqual(seen_from_other[0]["direction"], "in")
        self.assertEqual(seen_from_other[0]["other"]["id"], self.issue.id)

    def test_links_stay_inside_the_workspace_and_make_sense(self):
        self.client.force_authenticate(self.reporter)
        self.assertEqual(self.client.post(self.url(), {"kind": "relates", "target_id": self.foreign.id}, format="json").status_code, 400)
        self.assertEqual(self.client.post(self.url(), {"kind": "relates", "target_id": self.issue.id}, format="json").status_code, 400)
        self.assertEqual(self.client.post(self.url(), {"kind": "nope", "target_id": self.other.id}, format="json").status_code, 400)
        self.assertEqual(self.client.post(self.url(), {"kind": "relates", "target_id": self.other.id}, format="json").status_code, 201)
        self.assertEqual(self.client.post(self.url(), {"kind": "relates", "target_id": self.other.id}, format="json").status_code, 400)
        IssueRelation.objects.create(source=self.other, target=self.issue, kind="blocks")
        # The other issue already blocks this one, so this one cannot block it back.
        self.assertEqual(self.client.post(self.url(), {"kind": "blocks", "target_id": self.other.id}, format="json").status_code, 400)
        self.client.force_authenticate(self.member)
        self.assertEqual(self.client.post(self.url(self.other), {"kind": "relates", "target_id": self.issue.id}, format="json").status_code, 400)

    def test_who_can_add_and_remove(self):
        self.client.force_authenticate(self.member)
        self.assertEqual(self.client.post(self.url(), {"kind": "relates", "target_id": self.other.id}, format="json").status_code, 403)
        relation = IssueRelation.objects.create(source=self.issue, target=self.other, kind="relates")
        # The member created the other issue, so they may remove a link that shows on it.
        self.assertEqual(self.client.delete(reverse("issue-relation", args=[relation.id])).status_code, 204)

        relation = IssueRelation.objects.create(source=self.issue, target=self.other, kind="relates")
        stranger = User.objects.create_user(username="c-str", email="cstr@example.com", password="pw")
        Membership.objects.create(workspace=self.workspace, user=stranger, role="member")
        self.client.force_authenticate(stranger)
        self.assertEqual(self.client.delete(reverse("issue-relation", args=[relation.id])).status_code, 403)
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.delete(reverse("issue-relation", args=[relation.id])).status_code, 404)
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_deleting_an_issue_removes_its_links(self):
        IssueRelation.objects.create(source=self.issue, target=self.other, kind="duplicates")
        self.other.delete()
        self.assertFalse(IssueRelation.objects.exists())
