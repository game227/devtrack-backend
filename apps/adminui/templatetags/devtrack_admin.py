from django import template
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.urls import NoReverseMatch, reverse

register = template.Library()


def _changelist(model):
    try:
        return reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist")
    except NoReverseMatch:
        return None


@register.simple_tag
def devtrack_overview():
    """The figures on the admin's front page: people, workspaces, projects, and every issue on the line.

    A handful of COUNT queries; each figure links to its list when that model is in the admin.
    """
    from apps.issues.models import Issue
    from apps.projects.models import Project
    from apps.workspaces.models import Workspace

    User = get_user_model()
    users = User.objects.aggregate(total=Count("id"), active=Count("id", filter=Q(is_active=True)), staff=Count("id", filter=Q(is_staff=True)))
    workspaces = Workspace.objects.aggregate(total=Count("id"), shared=Count("id", filter=Q(is_personal=False)))
    projects = Project.objects.aggregate(total=Count("id"), active=Count("id", filter=Q(status=Project.Status.ACTIVE)))
    by_status = dict(Issue.objects.values_list("status").annotate(n=Count("id")).values_list("status", "n"))

    issue_list = _changelist(Issue)
    stations = [
        {
            "key": value,
            "label": label,
            "count": by_status.get(value, 0),
            "url": f"{issue_list}?status__exact={value}" if issue_list else None,
        }
        for value, label in Issue.Status.choices
    ]
    return {
        "figures": [
            {"label": "People", "value": users["total"], "note": f"{users['active']} active, {users['staff']} staff", "url": _changelist(User)},
            {"label": "Workspaces", "value": workspaces["total"], "note": f"{workspaces['shared']} shared", "url": _changelist(Workspace)},
            {"label": "Projects", "value": projects["total"], "note": f"{projects['active']} active", "url": _changelist(Project)},
            {"label": "Issues", "value": sum(by_status.values()), "note": f"{by_status.get(Issue.Status.DONE, 0)} done", "url": issue_list},
        ],
        "stations": stations,
    }
