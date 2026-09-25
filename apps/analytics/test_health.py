import datetime as dt

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.activities.models import Activity
from apps.cycles.models import Cycle
from apps.integrations.models import GitHubCommit, GitHubPullRequest, GitHubRepositoryLink
from apps.issues.models import Issue
from apps.projects.models import Project
from apps.workspaces.models import Membership, Workspace

from . import health

User = get_user_model()


class FactorFormulaTests(SimpleTestCase):
    """The formula, number in / number out."""

    def test_pace_is_judged_against_the_plan_not_against_100_percent(self):
        self.assertEqual(health.pace_score(done=5, total=10, expected_fraction=0.5), 100)  # exactly on plan
        self.assertEqual(health.pace_score(done=8, total=10, expected_fraction=0.5), 100)  # ahead is capped
        self.assertEqual(health.pace_score(done=2, total=10, expected_fraction=0.5), 40)  # behind
        self.assertEqual(health.pace_score(done=2, total=10, expected_fraction=1.0), 20)  # deadline reached

    def test_pace_is_not_judged_before_the_work_has_had_time_or_when_there_is_none(self):
        self.assertIsNone(health.pace_score(done=0, total=10, expected_fraction=0.05))
        self.assertIsNone(health.pace_score(done=0, total=0, expected_fraction=0.9))

    def test_flow_compares_closed_with_newly_opened(self):
        self.assertEqual(health.flow_score(closed=4, opened=4), 100)
        self.assertEqual(health.flow_score(closed=1, opened=4), 25)
        self.assertEqual(health.flow_score(closed=3, opened=0), 100)
        self.assertIsNone(health.flow_score(closed=0, opened=0))

    def test_no_deadlines_means_nothing_to_judge(self):
        self.assertIsNone(health.deadline_score([], dated_count=0))

    def test_all_on_time_is_perfect(self):
        self.assertEqual(health.deadline_score([], dated_count=6), 100)

    def test_one_slightly_late_issue_in_a_tiny_project_is_not_a_disaster(self):
        # v1 scored this 0 (1 of 1 overdue); smoothing keeps small samples from swinging to the extreme.
        self.assertGreaterEqual(health.deadline_score([(1, "medium")], dated_count=1), 70)

    def test_lateness_and_importance_both_cost_points(self):
        slight = health.deadline_score([(1, "low")], dated_count=5)
        very_late = health.deadline_score([(20, "low")], dated_count=5)
        very_late_urgent = health.deadline_score([(20, "urgent")], dated_count=5)
        self.assertGreater(slight, very_late)
        self.assertGreater(very_late, very_late_urgent)

    def test_everything_badly_overdue_scores_low_but_never_below_zero(self):
        score = health.deadline_score([(30, "urgent")] * 5, dated_count=5)
        self.assertLess(score, 30)
        self.assertGreaterEqual(score, 0)

    def test_no_open_bugs_is_perfect(self):
        self.assertEqual(health.bug_score([], open_issue_count=10), 100)

    def test_bug_pressure_depends_on_priority_and_age(self):
        medium = health.bug_score([("medium", 1)], open_issue_count=10)
        urgent = health.bug_score([("urgent", 1)], open_issue_count=10)
        old_urgent = health.bug_score([("urgent", 30)], open_issue_count=10)
        self.assertGreater(medium, urgent)
        self.assertGreater(urgent, old_urgent)

    def test_the_same_bug_matters_less_in_a_project_with_lots_of_open_work(self):
        small = health.bug_score([("high", 1)], open_issue_count=3)
        large = health.bug_score([("high", 1)], open_issue_count=60)
        self.assertGreater(large, small)

    def test_a_pile_of_urgent_bugs_bottoms_out_at_zero(self):
        self.assertEqual(health.bug_score([("urgent", 30)] * 20, open_issue_count=3), 0)

    def test_activity_has_a_grace_period_then_decays_linearly_to_zero(self):
        self.assertEqual(health.activity_score(0), 100)
        self.assertEqual(health.activity_score(health.ACTIVITY_GRACE_DAYS), 100)
        halfway = (health.ACTIVITY_GRACE_DAYS + health.ACTIVITY_ZERO_DAYS) // 2
        self.assertEqual(health.activity_score(halfway), 50)
        self.assertEqual(health.activity_score(health.ACTIVITY_ZERO_DAYS), 0)
        self.assertEqual(health.activity_score(90), 0)

    def test_stale_work_share(self):
        self.assertIsNone(health.stale_score(stale=0, in_flight=0))
        self.assertEqual(health.stale_score(stale=0, in_flight=4), 100)
        self.assertEqual(health.stale_score(stale=1, in_flight=1), 50)  # smoothing: one item is not "100% stale"
        self.assertLess(health.stale_score(stale=4, in_flight=4), health.stale_score(stale=1, in_flight=4))


class CombineTests(SimpleTestCase):
    def test_weights_are_renormalised_over_the_factors_that_apply(self):
        overall, breakdown = health.combine(
            {"task_progress": None, "deadline": 100, "bug_rate": 50, "development_activity": None, "flow": None}
        )
        by_key = {row["key"]: row for row in breakdown}
        self.assertEqual(by_key["task_progress"]["weight"], 0)
        self.assertEqual(by_key["deadline"]["weight"] + by_key["bug_rate"]["weight"], 100)
        # deadline 25 vs bug_rate 20 -> (100*25 + 50*20) / 45
        self.assertEqual(overall, round((100 * 25 + 50 * 20) / 45))

    def test_an_inapplicable_factor_neither_helps_nor_hurts(self):
        with_all = health.combine({k: 80 for k in health.WEIGHTS})[0]
        with_some = health.combine({"task_progress": 80, "deadline": None, "bug_rate": 80, "development_activity": None, "flow": None})[0]
        self.assertEqual(with_all, with_some)

    def test_points_add_up_to_the_score(self):
        overall, breakdown = health.combine({"task_progress": 60, "deadline": 90, "bug_rate": 70, "development_activity": 100, "flow": 40})
        self.assertAlmostEqual(sum(row["points"] for row in breakdown), overall, delta=0.6)

    def test_nothing_applicable_is_not_a_problem(self):
        overall, breakdown = health.combine({key: None for key in health.WEIGHTS})
        self.assertEqual(overall, 100)
        self.assertTrue(all(row["weight"] == 0 for row in breakdown))

    def test_status_thresholds(self):
        self.assertEqual(health.status_for(80), "healthy")
        self.assertEqual(health.status_for(79), "needs_attention")
        self.assertEqual(health.status_for(50), "needs_attention")
        self.assertEqual(health.status_for(49), "at_risk")

    def test_caps_only_report_the_ones_that_bit(self):
        self.assertEqual(health.apply_caps(90, {"critical_bug": 79, "abandoned": 49}), (49, ["critical_bug", "abandoned"]))
        self.assertEqual(health.apply_caps(60, {"critical_bug": 79}), (60, []))
        self.assertEqual(health.apply_caps(95, {}), (95, []))


class ProjectHealthScenarioTests(TestCase):
    """The whole thing through the API, on real rows."""

    def setUp(self):
        self.owner = User.objects.create_user(username="hsowner", email="hsowner@example.com", password="pw")
        self.workspace = Workspace.objects.create(name="HSWS", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role=Membership.Role.OWNER)
        self.project = Project.objects.create(
            workspace=self.workspace, name="P", owner=self.owner, status=Project.Status.ACTIVE
        )
        self.today = timezone.localdate()
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.url = reverse("project-health", kwargs={"pk": self.project.pk})

    def issue(self, title="I", days_old=0, **kwargs):
        issue = Issue.objects.create(project=self.project, title=title, reporter=self.owner, **kwargs)
        if days_old:
            stamp = timezone.now() - dt.timedelta(days=days_old)
            Issue.objects.filter(pk=issue.pk).update(created_at=stamp, updated_at=stamp)
        return issue

    def age_activity(self, days):
        Activity.objects.filter(workspace=self.workspace).update(created_at=timezone.now() - dt.timedelta(days=days))

    def health(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return response.data

    def factor(self, key):
        return self.health()["factors"][key]

    def test_response_carries_the_formula_version_and_an_explanation(self):
        self.issue()
        data = self.health()
        self.assertEqual(data["formula_version"], 2)
        self.assertEqual({row["key"] for row in data["breakdown"]}, set(health.WEIGHTS))
        self.assertEqual(sum(row["weight"] for row in data["breakdown"]), 100)
        for key in ("score", "status", "confidence", "factors", "capped_by", "risks", "risk_details"):
            self.assertIn(key, data)

    def test_a_brand_new_project_is_not_punished_for_having_done_nothing_yet(self):
        for number in range(6):
            self.issue(title=f"Fresh {number}")
        data = self.health()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["factors"]["deadline"], None)  # no deadlines set: nothing to judge

    def test_few_issues_mean_low_confidence(self):
        self.issue()
        self.assertEqual(self.health()["confidence"], "low")
        for number in range(6):
            self.issue(title=f"More {number}")
        self.assertEqual(self.health()["confidence"], "normal")

    # --- progress against the plan ---------------------------------------------------------------

    def test_progress_compares_with_the_project_dates(self):
        self.project.start_date = self.today - dt.timedelta(days=10)
        self.project.target_date = self.today + dt.timedelta(days=10)  # half the time has gone
        self.project.save()
        for number in range(10):
            self.issue(title=f"T{number}", status=Issue.Status.DONE if number < 2 else Issue.Status.TODO)
        detail = next(r for r in self.health()["breakdown"] if r["key"] == "task_progress")["detail"]
        self.assertEqual(detail["mode"], "dates")
        self.assertEqual(detail["expected_percent"], 50)
        self.assertEqual(self.factor("task_progress"), 40)  # 20% done when 50% was due

    def test_being_ahead_of_the_plan_scores_full_marks(self):
        self.project.start_date = self.today - dt.timedelta(days=10)
        self.project.target_date = self.today + dt.timedelta(days=10)
        self.project.save()
        for number in range(4):
            self.issue(title=f"T{number}", status=Issue.Status.DONE)
        self.issue(title="Open")
        self.assertEqual(self.factor("task_progress"), 100)

    def test_the_active_cycle_takes_precedence_over_the_project_dates(self):
        self.project.start_date = self.today - dt.timedelta(days=100)
        self.project.target_date = self.today + dt.timedelta(days=100)
        self.project.save()
        cycle = Cycle.objects.create(
            project=self.project, name="Sprint", start_date=self.today - dt.timedelta(days=5), end_date=self.today + dt.timedelta(days=5)
        )
        for number in range(4):
            self.issue(title=f"C{number}", cycle=cycle, status=Issue.Status.DONE if number < 3 else Issue.Status.TODO)
        self.issue(title="Outside the sprint")
        detail = next(r for r in self.health()["breakdown"] if r["key"] == "task_progress")["detail"]
        self.assertEqual(detail["mode"], "cycle")
        self.assertEqual((detail["done"], detail["total"]), (3, 4))
        self.assertEqual(self.factor("task_progress"), 100)  # 75% done, 50% due

    def test_a_project_younger_than_a_week_has_no_flow_verdict_yet(self):
        for number in range(4):
            self.issue(title=f"Opened {number}")
        self.assertIsNone(self.factor("task_progress"))

    def test_without_any_plan_progress_falls_back_to_recent_flow(self):
        Project.objects.filter(pk=self.project.pk).update(created_at=timezone.now() - dt.timedelta(days=30))
        for number in range(4):
            self.issue(title=f"Opened {number}")  # opened just now, nothing closed
        detail = next(r for r in self.health()["breakdown"] if r["key"] == "task_progress")["detail"]
        self.assertEqual(detail["mode"], "flow")
        self.assertEqual(self.factor("task_progress"), 0)
        self.issue(title="Closed", status=Issue.Status.DONE)
        self.assertGreater(self.factor("task_progress"), 0)

    # --- deadlines and bugs -----------------------------------------------------------------------

    def test_deadline_factor_reflects_how_late_things_are(self):
        self.issue(title="On time", due_date=self.today + dt.timedelta(days=3))
        self.issue(title="Late", due_date=self.today - dt.timedelta(days=9))
        details = next(r for r in self.health()["breakdown"] if r["key"] == "deadline")["detail"]
        self.assertEqual((details["dated"], details["overdue"]), (2, 1))
        self.assertTrue(0 < self.factor("deadline") < 100)

    def test_finished_late_work_is_not_overdue(self):
        self.issue(title="Done late", due_date=self.today - dt.timedelta(days=9), status=Issue.Status.DONE)
        self.assertEqual(self.factor("deadline"), 100)

    def test_bug_factor_ignores_finished_bugs_and_weighs_priority(self):
        self.issue(title="Fixed", type=Issue.Type.BUG, status=Issue.Status.DONE, priority=Issue.Priority.URGENT)
        self.assertEqual(self.factor("bug_rate"), 100)
        self.issue(title="Open urgent", type=Issue.Type.BUG, priority=Issue.Priority.URGENT)
        self.assertLess(self.factor("bug_rate"), 100)

    # --- activity ---------------------------------------------------------------------------------

    def test_a_quiet_project_loses_activity_points(self):
        self.issue()
        self.age_activity(30)
        self.assertEqual(self.factor("development_activity"), 0)

    def test_github_commits_keep_a_project_alive_even_when_devtrack_is_quiet(self):
        self.issue()
        self.age_activity(30)
        link = GitHubRepositoryLink.objects.create(
            project=self.project, github_repo_id=1, full_name="a/b", connected_by=self.owner
        )
        GitHubCommit.objects.create(repo_link=link, sha="c" * 40, message="work", url="https://x", committed_at=timezone.now() - dt.timedelta(days=1))
        data = self.health()
        self.assertEqual(data["factors"]["development_activity"], 100)
        detail = next(r for r in data["breakdown"] if r["key"] == "development_activity")["detail"]
        self.assertEqual(detail["source"], "github")

    def test_activity_is_only_judged_for_active_projects(self):
        self.issue()
        self.age_activity(60)
        for status in (Project.Status.PLANNED, Project.Status.PAUSED, Project.Status.COMPLETED, Project.Status.ARCHIVED):
            self.project.status = status
            self.project.save()
            self.assertIsNone(self.factor("development_activity"), status)
        self.assertNotIn("abandoned", self.health()["capped_by"])

    # --- stuck work -------------------------------------------------------------------------------

    def test_work_stuck_in_progress_or_review_is_scored_and_reported(self):
        self.issue(title="Stuck", status=Issue.Status.IN_PROGRESS, days_old=10)
        self.issue(title="Waiting", status=Issue.Status.IN_REVIEW, days_old=5)
        self.issue(title="Moving", status=Issue.Status.IN_PROGRESS)
        data = self.health()
        codes = {r["code"]: r for r in data["risk_details"]}
        self.assertEqual(codes["stale_in_progress"]["count"], 1)
        self.assertEqual(codes["stale_review"]["count"], 1)
        self.assertLess(data["factors"]["flow"], 100)

    def test_a_pull_request_open_for_too_long_is_a_risk(self):
        link = GitHubRepositoryLink.objects.create(
            project=self.project, github_repo_id=2, full_name="a/c", connected_by=self.owner
        )
        GitHubPullRequest.objects.create(
            repo_link=link, github_pr_id=1, number=1, title="Old", state="open", url="https://x",
            opened_at=timezone.now() - dt.timedelta(days=12),
        )
        GitHubPullRequest.objects.create(
            repo_link=link, github_pr_id=2, number=2, title="Fresh", state="open", url="https://x",
            opened_at=timezone.now() - dt.timedelta(days=1),
        )
        GitHubPullRequest.objects.create(
            repo_link=link, github_pr_id=3, number=3, title="Draft", state="open", draft=True, url="https://x",
            opened_at=timezone.now() - dt.timedelta(days=30),
        )
        codes = {r["code"]: r for r in self.health()["risk_details"]}
        self.assertEqual(codes["stale_pull_requests"]["count"], 1)  # drafts don't wait for anyone

    # --- caps --------------------------------------------------------------------------------------

    def test_an_old_urgent_bug_stops_a_project_from_being_called_healthy(self):
        # Lots of open work dilutes a single bug's weight, so the average alone would still say "healthy".
        for number in range(30):
            self.issue(title=f"Fine {number}")
        self.assertEqual(self.health()["status"], "healthy")
        self.issue(title="Nasty", type=Issue.Type.BUG, priority=Issue.Priority.URGENT, days_old=10)
        data = self.health()
        self.assertIn("critical_bug", data["capped_by"])
        self.assertLessEqual(data["score"], health.CAP_CRITICAL_BUG)
        self.assertNotEqual(data["status"], "healthy")

    def test_an_urgent_bug_filed_today_does_not_trigger_the_cap_yet(self):
        for number in range(30):
            self.issue(title=f"Fine {number}")
        self.issue(title="New", type=Issue.Type.BUG, priority=Issue.Priority.URGENT)
        self.assertNotIn("critical_bug", self.health()["capped_by"])

    def test_most_deadlines_blown_caps_the_score(self):
        for number in range(4):
            self.issue(title=f"Late {number}", due_date=self.today - dt.timedelta(days=20))
        self.issue(title="Fine", due_date=self.today + dt.timedelta(days=5))
        data = self.health()
        self.assertIn("mass_overdue", data["capped_by"])
        self.assertLessEqual(data["score"], health.CAP_MASS_OVERDUE)

    def test_an_abandoned_active_project_is_at_risk(self):
        for number in range(6):
            self.issue(title=f"Done {number}", status=Issue.Status.DONE)
        self.age_activity(45)
        data = self.health()
        self.assertIn("abandoned", data["capped_by"])
        self.assertEqual(data["status"], "at_risk")
        self.assertIn("no_recent_activity", {r["code"] for r in data["risk_details"]})
