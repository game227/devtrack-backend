"""What was left to do in a cycle at the end of each of its days.

Work is counted in story points when the cycle's issues have estimates, and in issues otherwise (an
issue without an estimate then counts as one). An issue is "left" on a day until its `completed_at`.
The issues are the cycle's issues today: moving an issue in or out of the cycle rewrites its history,
which keeps the chart simple and is what a team looking at it expects.
"""

import datetime as dt

from django.utils import timezone

MAX_DAYS = 120


def burndown(cycle, today=None):
    today = today or timezone.localdate()
    issues = list(cycle.issues.values("estimate", "completed_at", "status"))
    by_points = any(issue["estimate"] for issue in issues)

    def size(issue):
        return (issue["estimate"] or 0) if by_points else 1

    total = sum(size(issue) for issue in issues)
    days = min((cycle.end_date - cycle.start_date).days + 1, MAX_DAYS)
    points = []
    for offset in range(max(days, 0)):
        day = cycle.start_date + dt.timedelta(days=offset)
        if day > today:
            remaining = None
        else:
            day_end = timezone.make_aware(dt.datetime.combine(day + dt.timedelta(days=1), dt.time.min))
            remaining = sum(
                size(issue)
                for issue in issues
                if not (issue["completed_at"] and issue["completed_at"] < day_end)
            )
        ideal = round(total * (1 - offset / (days - 1)), 2) if days > 1 else 0
        points.append({"date": day.isoformat(), "remaining": remaining, "ideal": ideal})
    return {"unit": "points" if by_points else "issues", "total": total, "days": points}
