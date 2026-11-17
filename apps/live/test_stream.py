import asyncio
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.issues.models import Issue
from apps.projects.models import Project
from apps.workspaces.models import Membership, Workspace

from . import presence, stream

User = get_user_model()


def make_workspace(owner, name="W"):
    workspace = Workspace.objects.create(name=name, owner=owner)
    Membership.objects.create(workspace=workspace, user=owner, role="owner")
    return workspace


class TicketTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username="lt", email="lt@example.com", password="pw")
        self.outsider = User.objects.create_user(username="lt2", email="lt2@example.com", password="pw")
        self.workspace = make_workspace(self.user)
        self.client = APIClient()

    def test_members_get_a_single_use_ticket(self):
        self.client.force_authenticate(self.user)
        ticket = self.client.post(reverse("changes-ticket"), {"workspace": self.workspace.pk}, format="json").data["ticket"]
        self.assertEqual(stream.redeem_ticket(ticket), (self.user.pk, self.workspace.pk))
        self.assertIsNone(stream.redeem_ticket(ticket))
        self.assertIsNone(stream.redeem_ticket(ticket + "x"))
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.post(reverse("changes-ticket"), {"workspace": self.workspace.pk}, format="json").status_code, 403)

    def test_tickets_expire(self):
        ticket = stream.issue_ticket(self.user.pk, self.workspace.pk)
        with patch("django.core.signing.time.time", return_value=__import__("time").time() + stream.TICKET_SECONDS + 5):
            self.assertIsNone(stream.redeem_ticket(ticket))

    def test_stream_refuses_a_bad_ticket(self):
        self.assertEqual(self.client.get(reverse("changes-stream"), {"ticket": "nope"}).status_code, 403)


class StreamTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ls", email="ls@example.com", password="pw")
        self.workspace = make_workspace(self.user)
        self.project = Project.objects.create(workspace=self.workspace, name="P", owner=self.user)

    async def collect(self, rounds, between=None):
        events = []
        generator = stream._events(self.user.pk, self.workspace.pk, rounds=rounds)
        async for chunk in generator:
            events.append(chunk)
            if between and len(events) == 1:
                await between()
        return events

    def test_reports_changes_and_stops_when_membership_ends(self):
        def create_issue():
            from django.db import connection

            try:
                Issue.objects.create(project=self.project, title="new", reporter=self.user)
            finally:
                connection.close()

        async def change():
            from asgiref.sync import sync_to_async

            await sync_to_async(create_issue, thread_sensitive=False)()

        with patch.object(stream, "POLL_SECONDS", 0):
            events = asyncio.run(self.collect(rounds=1, between=change))
        self.assertEqual(events[0], "retry: 5000\n\n")
        self.assertTrue(events[1].startswith("event: changes\ndata: "))
        self.assertIn('"issues"', events[1])

        Membership.objects.filter(user=self.user).delete()
        with patch.object(stream, "POLL_SECONDS", 0):
            events = asyncio.run(self.collect(rounds=3))
        self.assertEqual(events[-1], "event: closed\ndata: {}\n\n")


class PresenceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.a = User.objects.create_user(username="pa", email="pa@example.com", password="pw")
        self.b = User.objects.create_user(username="pb", email="pb@example.com", password="pw")
        self.out = User.objects.create_user(username="pc", email="pc@example.com", password="pw")
        workspace = make_workspace(self.a)
        Membership.objects.create(workspace=workspace, user=self.b, role="member")
        self.issue = Issue.objects.create(project=Project.objects.create(workspace=workspace, name="P", owner=self.a), title="t", reporter=self.a)
        self.client = APIClient()

    def beat(self, user):
        self.client.force_authenticate(user)
        return self.client.post(reverse("presence"), {"issue": self.issue.pk}, format="json")

    def test_viewers_see_each_other_but_not_themselves(self):
        self.assertEqual(self.beat(self.a).data["viewers"], [])
        self.assertEqual([v["username"] for v in self.beat(self.b).data["viewers"]], ["pa"])
        self.assertEqual([v["username"] for v in self.beat(self.a).data["viewers"]], ["pb"])

    def test_outsiders_neither_see_nor_appear(self):
        self.beat(self.a)
        self.assertEqual(self.beat(self.out).status_code, 404)
        self.assertEqual(self.beat(self.b).data["viewers"][0]["username"], "pa")
        self.assertEqual(len(self.beat(self.b).data["viewers"]), 1)

    def test_old_beats_fade(self):
        presence.beat(self.issue.pk, self.a.pk, now=1000)
        self.assertEqual(presence.beat(self.issue.pk, self.b.pk, now=1000 + presence.FRESH_SECONDS + 1), [])
