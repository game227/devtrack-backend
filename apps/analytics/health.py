"""Project health score, formula v2.

Every factor is a 0-100 number, or ``None`` when there is nothing to judge (no deadlines, no
schedule, a paused project ...). The overall score is the weighted mean of the factors that *do*
apply, with the weights re-normalised — an inapplicable factor never drags a project down or props
it up. Hard caps then stop a serious problem from being averaged away.

The scoring functions are pure (numbers in, number out) so the formula can be read and tested
without a database; ``compute_project_health`` at the bottom gathers the numbers.

What changed from v1 (and why):
* "task progress" used to be plain done/total, which punished a project for having just started.
  It now compares progress with the plan (the active cycle, else the project's dates), or, with
  no plan at all, with the recent flow of closed vs. newly opened issues (judged only once the
  project is a week old).
* Overdue work is weighted by how late it is and how important, with a small-sample smoothing, so
  one issue a day late in a two-issue project no longer scores 0.
* Open bugs are weighted by priority and age and judged against the amount of open work, instead
  of a share of *all* issues (which finished work diluted).
* Activity counts GitHub commits and pull requests, not only what happens inside DevTrack, and is
  only judged for active projects.
* Work that is stuck (in progress / in review too long, pull requests waiting) is now a scored
  factor, not just a warning.
"""

from datetime import timedelta

from django.db.models import Max
from django.utils import timezone

from apps.activities.queries import project_timeline_queryset
from apps.cycles.models import Cycle
from apps.issues.models import Issue
from apps.projects.models import Project

FORMULA_VERSION = 2

# Relative importance of each factor before re-normalisation.
WEIGHTS = {
    "task_progress": 25,
    "deadline": 25,
    "bug_rate": 20,
    "development_activity": 20,
    "flow": 10,
}

HEALTHY_FROM = 80
NEEDS_ATTENTION_FROM = 50

STALE_IN_PROGRESS_DAYS = 7
STALE_REVIEW_DAYS = 3
STALE_PR_DAYS = 7
ACTIVITY_GRACE_DAYS = 3  # no penalty for a quiet spell this short
ACTIVITY_ZERO_DAYS = 21  # a fully silent project scores 0 from here on
ABANDONED_DAYS = 30
TOO_EARLY_FRACTION = 0.10  # under 10% of the schedule elapsed: too soon to call progress good or bad
FLOW_WINDOW_DAYS = 14
FLOW_MIN_PROJECT_AGE_DAYS = 7  # a brand-new project is all freshly opened issues; that says nothing yet
DEADLINE_FULL_PENALTY_DAYS = 14  # this late (or later) an overdue issue counts fully
DEADLINE_MIN_PENALTY = 0.3  # even one day late is not nothing
DEADLINE_SMOOTHING = 2  # phantom on-time issues that keep tiny samples from swinging to 0
IMPORTANT_MULTIPLIER = 1.5
BUG_WEIGHTS = {"urgent": 4.0, "high": 3.0, "medium": 1.5, "low": 1.0, "none": 1.0}
BUG_OLD_DAYS = 14
BUG_OLD_MULTIPLIER = 1.5
BUG_CAPACITY_PER_OPEN_ISSUE = 1.5
BUG_CAPACITY_BASE = 6.0
LOW_CONFIDENCE_BELOW = 5  # fewer issues than this: the score is a rough guide only

CAP_CRITICAL_BUG = 79
CAP_MASS_OVERDUE = 64
CAP_ABANDONED = 49
CRITICAL_BUG_DAYS = 7
MASS_OVERDUE_MIN = 3
MASS_OVERDUE_SHARE = 0.5


def _clamp(value, low=0, high=100):
    return max(low, min(high, value))


# --- pure factor scores ----------------------------------------------------------------------


def pace_score(done, total, expected_fraction):
    """Progress against the plan: 100 when at or ahead of schedule, proportionally less when behind."""
    if total == 0 or expected_fraction < TOO_EARLY_FRACTION:
        return None
    return round(_clamp(done / total / expected_fraction * 100))


def flow_score(closed, opened):
    """No plan to compare with: are we closing issues about as fast as new ones arrive?"""
    if opened == 0:
        return 100 if closed > 0 else None
    return round(_clamp(closed / opened * 100))


def deadline_score(overdue, dated_count):
    """`overdue` is a list of (days_late, priority) for open issues past their due date."""
    if dated_count == 0:
        return None
    penalty = 0.0
    for days_late, priority in overdue:
        severity = _clamp(days_late / DEADLINE_FULL_PENALTY_DAYS, DEADLINE_MIN_PENALTY, 1.0)
        if priority in ("high", "urgent"):
            severity *= IMPORTANT_MULTIPLIER
        penalty += severity
    return round(100 * (1 - min(1.0, penalty / (dated_count + DEADLINE_SMOOTHING))))


def bug_score(open_bugs, open_issue_count):
    """`open_bugs` is a list of (priority, age_days). Pressure is judged against how much work is open."""
    pressure = 0.0
    for priority, age_days in open_bugs:
        weight = BUG_WEIGHTS.get(priority, 1.0)
        if age_days > BUG_OLD_DAYS:
            weight *= BUG_OLD_MULTIPLIER
        pressure += weight
    capacity = open_issue_count * BUG_CAPACITY_PER_OPEN_ISSUE + BUG_CAPACITY_BASE
    return round(100 * (1 - min(1.0, pressure / capacity)))


def activity_score(days_since):
    """Full marks within the grace period, then a straight line down to 0."""
    if days_since <= ACTIVITY_GRACE_DAYS:
        return 100
    span = ACTIVITY_ZERO_DAYS - ACTIVITY_GRACE_DAYS
    return round(_clamp(100 * (1 - (days_since - ACTIVITY_GRACE_DAYS) / span)))


def stale_score(stale, in_flight):
    """Share of in-flight work that has stalled (one phantom healthy item smooths tiny samples)."""
    if in_flight == 0:
        return None
    return round(100 * (1 - stale / (in_flight + 1)))


# --- combining --------------------------------------------------------------------------------


def combine(scores):
    """Weighted mean over the applicable factors. Returns (overall, breakdown)."""
    applicable = {key: score for key, score in scores.items() if score is not None}
    total_weight = sum(WEIGHTS[key] for key in applicable)
    if total_weight == 0:
        # Nothing to judge at all: there is no evidence of a problem.
        return 100, [{"key": key, "score": None, "weight": 0, "points": 0.0} for key in WEIGHTS]
    breakdown = []
    overall = 0.0
    for key in WEIGHTS:
        score = scores.get(key)
        effective = WEIGHTS[key] / total_weight * 100 if score is not None and total_weight else 0.0
        points = (score or 0) * effective / 100
        overall += points
        breakdown.append({"key": key, "score": score, "weight": round(effective), "points": round(points, 1)})
    return round(overall), breakdown


def status_for(score):
    if score >= HEALTHY_FROM:
        return "healthy"
    if score >= NEEDS_ATTENTION_FROM:
        return "needs_attention"
    return "at_risk"


def apply_caps(overall, caps):
    """`caps` maps a reason code to the ceiling it imposes. Returns (score, reasons that actually bit)."""
    capped = min([overall] + list(caps.values()))
    return capped, [code for code, ceiling in caps.items() if ceiling < overall]


# --- gathering the numbers ---------------------------------------------------------------------


def _latest(*values):
    values = [value for value in values if value is not None]
    return max(values) if values else None


def _last_signal(project):
    """The newest sign of life: DevTrack activity, a GitHub commit or a pull request update."""
    from apps.integrations.models import GitHubCommit, GitHubPullRequest

    timeline = project_timeline_queryset(project).aggregate(latest=Max("created_at"))["latest"]
    commits = GitHubCommit.objects.filter(repo_link__project=project)
    commit_time = _latest(
        commits.aggregate(latest=Max("committed_at"))["latest"],
        commits.aggregate(latest=Max("created_at"))["latest"],
    )
    pr_time = GitHubPullRequest.objects.filter(repo_link__project=project).aggregate(latest=Max("updated_at"))["latest"]
    github_time = _latest(commit_time, pr_time)
    last = _latest(timeline, github_time)
    if last is None:
        return project.created_at, "devtrack"
    return last, "github" if github_time is not None and github_time == last else "devtrack"


def _schedule(project, issues, today, now):
    """(score, detail) for the progress factor, using the best plan available."""
    cycle = Cycle.objects.filter(project=project, start_date__lte=today, end_date__gte=today).order_by("-start_date").first()
    if cycle is not None:
        scope, start, end, mode = issues.filter(cycle=cycle), cycle.start_date, cycle.end_date, "cycle"
    elif project.start_date and project.target_date and project.start_date <= today:
        scope, start, end, mode = issues, project.start_date, project.target_date, "dates"
    else:
        scope = None

    if scope is not None:
        total = scope.count()
        done = scope.filter(status=Issue.Status.DONE).count()
        span = max(1, (end - start).days)
        expected = _clamp((today - start).days / span, 0, 1)
        return pace_score(done, total, expected), {
            "mode": mode,
            "done": done,
            "total": total,
            "expected_percent": round(expected * 100),
        }

    project_age_days = (today - timezone.localdate(project.created_at)).days
    window_start = now - timedelta(days=FLOW_WINDOW_DAYS)
    opened = issues.filter(created_at__gte=window_start).count()
    closed = issues.filter(status=Issue.Status.DONE, updated_at__gte=window_start).count()
    detail = {"mode": "flow", "closed": closed, "opened": opened, "days": FLOW_WINDOW_DAYS}
    if project_age_days < FLOW_MIN_PROJECT_AGE_DAYS:
        return None, detail
    return flow_score(closed, opened), detail


def compute_project_health(project, now=None):
    from apps.integrations.models import GitHubPullRequest

    now = now or timezone.now()
    today = timezone.localdate(now)
    issues = Issue.objects.filter(project=project)
    total = issues.count()
    open_issues = issues.exclude(status=Issue.Status.DONE)
    open_count = open_issues.count()

    # 1. progress against the plan
    progress, progress_detail = _schedule(project, issues, today, now)

    # 2. deadlines
    dated = issues.exclude(due_date__isnull=True)
    overdue_rows = list(open_issues.filter(due_date__lt=today).values_list("due_date", "priority"))
    overdue = [((today - due).days, priority) for due, priority in overdue_rows]
    dated_count = dated.count()
    deadline = deadline_score(overdue, dated_count)

    # 3. bugs
    open_bugs_qs = open_issues.filter(type=Issue.Type.BUG)
    bug_rows = [
        (priority, (today - timezone.localdate(created)).days)
        for priority, created in open_bugs_qs.values_list("priority", "created_at")
    ]
    bugs = bug_score(bug_rows, open_count)

    # 4. activity (only meaningful while a project is active)
    last_signal, signal_source = _last_signal(project)
    days_since = max(0, (today - timezone.localdate(last_signal)).days)
    is_active = project.status == Project.Status.ACTIVE
    activity = activity_score(days_since) if is_active else None

    # 5. stuck work
    in_progress = issues.filter(status=Issue.Status.IN_PROGRESS)
    in_review = issues.filter(status=Issue.Status.IN_REVIEW)
    stale_progress_count = in_progress.filter(updated_at__lt=now - timedelta(days=STALE_IN_PROGRESS_DAYS)).count()
    stale_review_count = in_review.filter(updated_at__lt=now - timedelta(days=STALE_REVIEW_DAYS)).count()
    open_prs = GitHubPullRequest.objects.filter(
        repo_link__project=project, state=GitHubPullRequest.State.OPEN, draft=False
    )
    stale_pr_cutoff = now - timedelta(days=STALE_PR_DAYS)
    stale_pr_count = sum(1 for opened_at, created_at in open_prs.values_list("opened_at", "created_at") if (opened_at or created_at) < stale_pr_cutoff)
    in_flight = in_progress.count() + in_review.count() + open_prs.count()
    flow = stale_score(stale_progress_count + stale_review_count + stale_pr_count, in_flight)

    scores = {
        "task_progress": progress,
        "deadline": deadline,
        "bug_rate": bugs,
        "development_activity": activity,
        "flow": flow,
    }
    overall, breakdown = combine(scores)

    details = {
        "task_progress": progress_detail,
        "deadline": {"dated": dated_count, "overdue": len(overdue)},
        "bug_rate": {"open_bugs": len(bug_rows), "urgent": sum(1 for p, _ in bug_rows if p == "urgent")},
        "development_activity": {"days_since": days_since, "source": signal_source, "applies": is_active},
        "flow": {
            "stale": stale_progress_count + stale_review_count + stale_pr_count,
            "in_flight": in_flight,
        },
    }
    for entry in breakdown:
        entry["detail"] = details[entry["key"]]

    # Caps: a serious problem must not be averaged away by good numbers elsewhere.
    caps = {}
    if any(priority == "urgent" and age > CRITICAL_BUG_DAYS for priority, age in bug_rows):
        caps["critical_bug"] = CAP_CRITICAL_BUG
    open_dated = len([1 for _ in open_issues.exclude(due_date__isnull=True).values_list("id", flat=True)])
    if len(overdue) >= MASS_OVERDUE_MIN and open_dated and len(overdue) / open_dated >= MASS_OVERDUE_SHARE:
        caps["mass_overdue"] = CAP_MASS_OVERDUE
    if is_active and days_since >= ABANDONED_DAYS:
        caps["abandoned"] = CAP_ABANDONED
    score, capped_by = apply_caps(overall, caps)

    # Each risk is reported twice: as an English sentence (kept for existing clients) and as a
    # structured code + counts the UI can localize.
    risks, risk_details = [], []

    def add_risk(code, text, **extra):
        risks.append(text)
        risk_details.append({"code": code, **extra})

    if stale_progress_count:
        add_risk(
            "stale_in_progress",
            f"{stale_progress_count} task(s) have been in progress for more than {STALE_IN_PROGRESS_DAYS} days.",
            count=stale_progress_count,
            days=STALE_IN_PROGRESS_DAYS,
        )
    if stale_review_count:
        add_risk(
            "stale_review",
            f"{stale_review_count} task(s) have been waiting for review for more than {STALE_REVIEW_DAYS} days.",
            count=stale_review_count,
            days=STALE_REVIEW_DAYS,
        )
    if stale_pr_count:
        add_risk(
            "stale_pull_requests",
            f"{stale_pr_count} pull request(s) have been open for more than {STALE_PR_DAYS} days.",
            count=stale_pr_count,
            days=STALE_PR_DAYS,
        )
    if overdue:
        add_risk("overdue", f"{len(overdue)} issue(s) are past their due date.", count=len(overdue))
    urgent_bug_count = sum(1 for priority, _ in bug_rows if priority in ("high", "urgent"))
    if urgent_bug_count:
        add_risk("urgent_bugs", f"{urgent_bug_count} unresolved high/urgent priority bug(s).", count=urgent_bug_count)
    if is_active and days_since >= 14:
        add_risk("no_recent_activity", f"No activity for {days_since} days.", count=days_since, days=days_since)

    return {
        "score": score,
        "status": status_for(score),
        "formula_version": FORMULA_VERSION,
        "confidence": "low" if total < LOW_CONFIDENCE_BELOW else "normal",
        "factors": scores,
        "breakdown": breakdown,
        "capped_by": capped_by,
        "risks": risks,
        "risk_details": risk_details,
    }
