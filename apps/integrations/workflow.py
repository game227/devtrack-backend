"""How GitHub activity moves DevTrack issues.

Status only ever moves *forward* here (backlog -> todo -> in progress -> in review -> done): a late
webhook, a re-synced old commit or a reopened PR must never drag finished work back, and a person's
manual move to a later status always wins over automation.
"""

from django.utils.dateparse import parse_datetime

from apps.issues.models import Issue

STATUS_ORDER = [
    Issue.Status.BACKLOG,
    Issue.Status.TODO,
    Issue.Status.IN_PROGRESS,
    Issue.Status.IN_REVIEW,
    Issue.Status.DONE,
]


def status_rank(status):
    return STATUS_ORDER.index(status)


def advance_issue(issue, target, actor):
    """Move `issue` to `target` if that is forward progress. Returns whether anything changed."""
    if status_rank(target) <= status_rank(issue.status):
        return False
    issue._actor = actor  # attributes the generic "moved" activity to the developer, not the reporter
    issue.status = target
    issue.save(update_fields=["status", "updated_at"])
    return True


def parse_github_datetime(value):
    """GitHub's ISO-8601 timestamps as aware datetimes; None when missing or malformed."""
    if not value or not isinstance(value, str):
        return None
    try:
        return parse_datetime(value)
    except ValueError:
        return None


def branch_from_ref(ref):
    prefix = "refs/heads/"
    return ref[len(prefix):] if isinstance(ref, str) and ref.startswith(prefix) else ""
