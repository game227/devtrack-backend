from types import SimpleNamespace

from django.test import SimpleTestCase
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.issues.models import Issue

from .filters import StableOrderingFilter


class StableOrderingFilterTests(SimpleTestCase):
    def sql(self, query_string):
        request = Request(APIRequestFactory().get(f"/issues/?{query_string}"))
        view = SimpleNamespace(ordering_fields=["due_date", "completed_at"], ordering=None)
        return str(StableOrderingFilter().filter_queryset(request, Issue.objects.all(), view).query)

    def test_empty_values_go_last_and_ties_are_broken_by_id(self):
        sql = self.sql("ordering=-due_date")
        self.assertIn('"due_date" DESC NULLS LAST', sql)
        self.assertTrue(sql.rstrip().endswith('"issues_issue"."id" DESC'), sql)
        self.assertIn('"due_date" ASC NULLS LAST', self.sql("ordering=due_date"))

    def test_fields_that_are_not_allowed_are_ignored(self):
        sql = self.sql("ordering=password")
        self.assertNotIn("password", sql)
