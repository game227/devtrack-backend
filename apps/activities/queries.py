from django.contrib.contenttypes.models import ContentType
from django.db.models import Q

from apps.comments.models import Comment
from apps.issues.models import Issue
from apps.projects.models import Project

from .models import Activity


def project_timeline_queryset(project):
    """Every Activity that belongs to a project.

    Activity only has a workspace FK, not a project one — a project's timeline is
    every Activity whose target is the project itself, one of its issues, or a
    comment on either of those. The id sets are passed as lazy ``values("id")``
    subqueries, so nothing is materialized in Python however large the project is.
    """
    project_ct = ContentType.objects.get_for_model(Project)
    issue_ct = ContentType.objects.get_for_model(Issue)
    comment_ct = ContentType.objects.get_for_model(Comment)

    issue_ids = Issue.objects.filter(project=project).values("id")
    comment_ids = Comment.objects.filter(
        Q(content_type=issue_ct, object_id__in=issue_ids) | Q(content_type=project_ct, object_id=project.id)
    ).values("id")

    return Activity.objects.filter(
        Q(content_type=project_ct, object_id=project.id)
        | Q(content_type=issue_ct, object_id__in=issue_ids)
        | Q(content_type=comment_ct, object_id__in=comment_ids)
    )
