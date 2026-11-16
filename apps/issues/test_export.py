import csv
import io

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.projects.models import Label, Project
from apps.workspaces.models import Membership, Workspace

from .export import safe_cell
from .models import Issue
from .views import IssueExportThrottle

User = get_user_model()


def read_csv(response):
    body = b"".join(response.streaming_content).decode("utf-8")
    assert body.startswith("﻿"), "the file starts with a byte-order mark for Excel"
    return list(csv.reader(io.StringIO(body[1:])))


class IssueExportTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user(username="xowner", email="xowner@example.com", password="pw")
        self.outsider = User.objects.create_user(username="xout", email="xout@example.com", password="pw")
        self.workspace = Workspace.objects.create(name="Export WS", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role=Membership.Role.OWNER)
        self.project = Project.objects.create(workspace=self.workspace, name="Mobile App", owner=self.owner)
        self.other = Project.objects.create(workspace=self.workspace, name="Site", owner=self.owner)
        label = Label.objects.create(workspace=self.workspace, name="ui", color="#123456")
        self.first = Issue.objects.create(
            project=self.project, title="Login button", reporter=self.owner, assignee=self.owner, status="todo", priority="high"
        )
        self.first.labels.add(label)
        Issue.objects.create(project=self.project, title="Crash on start", reporter=self.owner, status="done", type="bug")
        Issue.objects.create(project=self.other, title="Footer links", reporter=self.owner)
        self.url = reverse("issue-export")
        self.client = APIClient()

    def test_exports_the_project_as_a_csv_attachment(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get(self.url, {"project": self.project.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertRegex(response["Content-Disposition"], r'^attachment; filename="mobile-app-issues-\d{4}-\d{2}-\d{2}\.csv"$')
        self.assertEqual(response["Cache-Control"], "no-store")
        rows = read_csv(response)
        self.assertEqual(rows[0][:4], ["Number", "Title", "Project", "Status"])
        titles = {row[1] for row in rows[1:]}
        self.assertEqual(titles, {"Login button", "Crash on start"})
        login = next(row for row in rows if row[1] == "Login button")
        self.assertEqual(login[0], f"#{self.first.number}")
        self.assertEqual(login[3:7], ["Todo", "High", "Task", "xowner"])
        self.assertEqual(login[8], "ui")

    def test_applies_the_same_filters_as_the_list(self):
        self.client.force_authenticate(self.owner)
        rows = read_csv(self.client.get(self.url, {"project": self.project.id, "status": "done"}))
        self.assertEqual([row[1] for row in rows[1:]], ["Crash on start"])
        rows = read_csv(self.client.get(self.url, {"workspace": self.workspace.id, "assignee": "me"}))
        self.assertEqual([row[1] for row in rows[1:]], ["Login button"])

    def test_workspace_export_names_the_project_of_each_row(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get(self.url, {"workspace": self.workspace.id})
        self.assertIn('filename="export-ws-issues-', response["Content-Disposition"])
        projects = {row[1]: row[2] for row in read_csv(response)[1:]}
        self.assertEqual(projects["Footer links"], "Site")
        self.assertEqual(projects["Login button"], "Mobile App")

    def test_headers_and_values_follow_the_language(self):
        self.client.force_authenticate(self.owner)
        rows = read_csv(self.client.get(self.url, {"project": self.project.id, "status": "todo", "lang": "uz"}))
        self.assertEqual(rows[0][:4], ["Raqam", "Sarlavha", "Loyiha", "Holat"])
        self.assertEqual(rows[1][3:6], ["Qilinadigan", "Yuqori", "Topshiriq"])
        rows = read_csv(self.client.get(self.url, {"project": self.project.id, "status": "todo", "lang": "xx"}))
        self.assertEqual(rows[0][0], "Number")

    def test_cells_that_look_like_formulas_are_defused(self):
        Issue.objects.create(project=self.project, title='=HYPERLINK("http://evil.test","x")', reporter=self.owner)
        self.client.force_authenticate(self.owner)
        rows = read_csv(self.client.get(self.url, {"project": self.project.id}))
        self.assertIn("'=HYPERLINK(\"http://evil.test\",\"x\")", [row[1] for row in rows])
        for raw in ["=1+1", "+1", "-1", "@SUM(A1)", "\tx", "\rx"]:
            self.assertEqual(safe_cell(raw), "'" + raw)
        self.assertEqual(safe_cell("plain"), "plain")
        self.assertEqual(safe_cell(None), "")

    def test_only_members_can_export(self):
        response = self.client.get(self.url, {"project": self.project.id})
        self.assertEqual(response.status_code, 401)
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(self.url, {"project": self.project.id}).status_code, 403)
        self.assertEqual(self.client.get(self.url, {"workspace": self.workspace.id}).status_code, 403)
        self.assertEqual(self.client.get(self.url).status_code, 400)
        self.assertEqual(self.client.get(self.url, {"project": "abc"}).status_code, 400)

    def test_exports_are_rate_limited(self):
        original = IssueExportThrottle.THROTTLE_RATES
        IssueExportThrottle.THROTTLE_RATES = {**original, "issue_export": "2/hour"}
        self.addCleanup(setattr, IssueExportThrottle, "THROTTLE_RATES", original)
        self.client.force_authenticate(self.owner)
        for _ in range(2):
            self.assertEqual(self.client.get(self.url, {"project": self.project.id}).status_code, 200)
        self.assertEqual(self.client.get(self.url, {"project": self.project.id}).status_code, 429)
