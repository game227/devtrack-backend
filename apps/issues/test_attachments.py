import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.projects.models import Project
from apps.workspaces.models import Membership, Workspace

from .attachments import MAX_ATTACHMENTS_PER_ISSUE, clean_name, sniff
from .models import Issue, IssueAttachment

User = get_user_model()
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.7\n" + b"x" * 64

MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=MEDIA, ATTACHMENT_MAX_BYTES=1024)
class AttachmentTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.reporter = User.objects.create_user(username="a-rep", email="arep@example.com", password="pw")
        self.member = User.objects.create_user(username="a-mem", email="amem@example.com", password="pw")
        self.other = User.objects.create_user(username="a-oth", email="aoth@example.com", password="pw")
        self.admin = User.objects.create_user(username="a-adm", email="aadm@example.com", password="pw")
        self.outsider = User.objects.create_user(username="a-out", email="aout@example.com", password="pw")
        self.workspace = Workspace.objects.create(name="AW", owner=self.reporter)
        for user, role in [(self.reporter, "owner"), (self.member, "member"), (self.other, "member"), (self.admin, "admin")]:
            Membership.objects.create(workspace=self.workspace, user=user, role=role)
        project = Project.objects.create(workspace=self.workspace, name="P", owner=self.reporter)
        self.issue = Issue.objects.create(project=project, title="t", reporter=self.reporter)
        self.url = reverse("issue-attachments", args=[self.issue.id])
        self.client = APIClient()

    def upload(self, user, name="shot.png", content=PNG):
        self.client.force_authenticate(user)
        return self.client.post(self.url, {"file": SimpleUploadedFile(name, content, content_type="text/html")}, format="multipart")

    def test_members_upload_list_and_download(self):
        response = self.upload(self.member, name="../../etc/Screen\x07 shot.png")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["name"], "Screen shot.png")
        self.assertEqual(response.data["content_type"], "image/png")
        self.assertTrue(response.data["is_image"])
        stored = IssueAttachment.objects.get()
        self.assertRegex(stored.file.name, r"^attachments/[0-9a-f]{32}$")

        self.client.force_authenticate(self.other)
        self.assertEqual(len(self.client.get(self.url).data), 1)
        download = self.client.get(reverse("issue-attachment-download", args=[stored.id]))
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download["Content-Type"], "image/png")
        self.assertTrue(download["Content-Disposition"].startswith("attachment;"))
        self.assertEqual(download["X-Content-Type-Options"], "nosniff")
        self.assertIn("sandbox", download["Content-Security-Policy"])
        self.assertEqual(b"".join(download.streaming_content), PNG)

    def test_only_safe_types_whose_name_matches_the_content(self):
        self.assertEqual(self.upload(self.member, "report.pdf", PDF).status_code, 201)
        self.assertEqual(self.upload(self.member, "notes.md", "# Qaydlar — ✓".encode()).status_code, 201)
        self.assertEqual(self.upload(self.member, "page.html", b"<script>alert(1)</script>").status_code, 400)
        self.assertEqual(self.upload(self.member, "logo.svg", b"<svg onload=alert(1)>").status_code, 400)
        self.assertEqual(self.upload(self.member, "fake.png", b"<html>hi</html>").status_code, 400)
        self.assertEqual(self.upload(self.member, "photo.png", PDF).status_code, 400)
        self.assertEqual(self.upload(self.member, "app.exe", b"MZ\x90\x00\x03").status_code, 400)
        self.assertEqual(self.upload(self.member, "empty.txt", b"").status_code, 400)

    def test_size_and_count_limits(self):
        self.assertEqual(self.upload(self.member, "big.txt", b"a" * 2000).status_code, 400)
        IssueAttachment.objects.bulk_create(
            IssueAttachment(issue=self.issue, file=f"attachments/x{i}", name="x.txt", content_type="text/plain", size=1)
            for i in range(MAX_ATTACHMENTS_PER_ISSUE)
        )
        self.assertEqual(self.upload(self.member).status_code, 400)

    def test_outsiders_see_nothing(self):
        self.upload(self.member)
        attachment = IssueAttachment.objects.get()
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.get(reverse("issue-attachment-download", args=[attachment.id])).status_code, 404)
        self.assertEqual(self.upload(self.outsider).status_code, 404)
        self.assertEqual(self.client.delete(reverse("issue-attachment", args=[attachment.id])).status_code, 404)

    def test_who_may_delete_and_the_file_goes_too(self):
        attachment_id = self.upload(self.member).data["id"]
        path = IssueAttachment.objects.get().file.path
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.delete(reverse("issue-attachment", args=[attachment_id])).status_code, 403)
        for user in (self.member, self.reporter, self.admin):
            attachment_id = attachment_id if user is self.member else self.upload(self.other).data["id"]
            self.client.force_authenticate(user)
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.client.delete(reverse("issue-attachment", args=[attachment_id])).status_code, 204)
        import os

        self.assertFalse(os.path.exists(path))
        self.assertFalse(IssueAttachment.objects.exists())

    def test_helpers(self):
        self.assertEqual(sniff(b"GIF89a..."), "gif")
        self.assertEqual(sniff(b"RIFF\x00\x00\x00\x00WEBPVP8 "), "webp")
        self.assertEqual(sniff("ok ✓".encode()[:-1]), "text")
        self.assertIsNone(sniff(b"\x00\x01binary"))
        self.assertEqual(clean_name(""), "file")
        self.assertEqual(len(clean_name("a" * 300 + ".txt")), 120)
        self.assertTrue(clean_name("a" * 300 + ".txt").endswith(".txt"))


@override_settings(MAX_UPLOAD_BYTES=100, ATTACHMENT_MAX_BYTES=1024, MEDIA_ROOT=MEDIA)
class RequestSizeTests(TestCase):
    def test_attachment_endpoint_has_its_own_request_limit(self):
        user = User.objects.create_user(username="rs", email="rs@example.com", password="pw")
        workspace = Workspace.objects.create(name="R", owner=user)
        Membership.objects.create(workspace=workspace, user=user, role="owner")
        issue = Issue.objects.create(project=Project.objects.create(workspace=workspace, name="P", owner=user), title="t", reporter=user)
        client = APIClient()
        client.force_authenticate(user)
        ok = client.post(reverse("issue-attachments", args=[issue.id]), {"file": SimpleUploadedFile("a.txt", b"x" * 500)}, format="multipart")
        self.assertEqual(ok.status_code, 201)
        too_big = client.post(reverse("issue-attachments", args=[issue.id]), {"file": SimpleUploadedFile("a.txt", b"x" * 200_000)}, format="multipart")
        self.assertEqual(too_big.status_code, 400)
