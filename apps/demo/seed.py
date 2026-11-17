"""A small, believable workspace for one demo visitor, made in one transaction."""

import datetime as dt
import secrets

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from apps.comments.models import Comment
from apps.cycles.models import Cycle
from apps.issues.models import ChecklistItem, Issue, IssueRelation
from apps.projects.models import Label, Project, ProjectMember
from apps.workspaces.models import Membership, Workspace

from .models import DemoAccount

User = get_user_model()

TEAMMATES = [("aziza", "Aziza", "Karimova"), ("timur", "Timur", "Rakhimov")]
ISSUES = [
    # title, status, priority, type, estimate, who (0 = visitor, 1/2 = teammates), label
    ("Sign in with a one-time code", "done", "high", "feature", 5, 1, "backend"),
    ("Crash when the cart is empty", "done", "urgent", "bug", 3, 2, "mobile"),
    ("Payment receipt by email", "in_review", "medium", "feature", 3, 1, "backend"),
    ("Dark theme for the checkout", "in_progress", "low", "improvement", 2, 0, "design"),
    ("Order history screen", "in_progress", "high", "feature", 8, 2, "mobile"),
    ("Retry failed card payments", "todo", "high", "feature", 5, 0, "backend"),
    ("Delivery time is shown in UTC", "todo", "medium", "bug", 1, 1, "mobile"),
    ("Promo codes", "backlog", "medium", "feature", 8, None, "backend"),
    ("Write the API docs for partners", "backlog", "low", "chore", 3, None, None),
    ("Speed up the product search", "backlog", "none", "improvement", 5, None, "backend"),
]


@transaction.atomic
def create_demo(ttl):
    suffix = secrets.token_hex(4)
    now = timezone.now()
    visitor = User.objects.create_user(username=f"demo-{suffix}", email=f"demo-{suffix}@demo.invalid", first_name="Demo")
    visitor.set_unusable_password()
    visitor.save(update_fields=["password"])
    people = [visitor]
    for handle, first, last in TEAMMATES:
        mate = User.objects.create_user(
            username=f"{handle}-{suffix}", email=f"{handle}-{suffix}@demo.invalid", first_name=first, last_name=last
        )
        mate.set_unusable_password()
        mate.save(update_fields=["password"])
        people.append(mate)
    for person in people:
        DemoAccount.objects.create(user=person, expires_at=now + ttl)

    # Every new account gets an empty personal workspace; in a demo it would only hide the sample one.
    Workspace.objects.filter(owner__in=people, is_personal=True).delete()
    workspace = Workspace.objects.create(name="Demo: Bozor app", owner=visitor)
    Membership.objects.create(workspace=workspace, user=visitor, role=Membership.Role.OWNER)
    for mate in people[1:]:
        Membership.objects.create(workspace=workspace, user=mate, role=Membership.Role.MEMBER)

    today = timezone.localdate()
    project = Project.objects.create(
        workspace=workspace,
        name="Bozor mobile app",
        description="The shop's app for Android and iOS: catalogue, cart, payments and delivery.",
        status=Project.Status.ACTIVE,
        owner=visitor,
        start_date=today - dt.timedelta(days=20),
        target_date=today + dt.timedelta(days=25),
    )
    for person in people:
        ProjectMember.objects.create(project=project, user=person)
    labels = {
        name: Label.objects.create(workspace=workspace, name=name, color=color)
        for name, color in [("backend", "#3354c4"), ("mobile", "#197a43"), ("design", "#7a4bcf")]
    }
    cycle = Cycle.objects.create(project=project, name="Sprint 4", start_date=today - dt.timedelta(days=6), end_date=today + dt.timedelta(days=7))

    issues = []
    for index, (title, status, priority, kind, estimate, who, label) in enumerate(ISSUES):
        issue = Issue.objects.create(
            project=project,
            title=title,
            status=status,
            priority=priority,
            type=kind,
            estimate=estimate,
            reporter=visitor if index % 3 == 0 else people[1 + index % 2],
            assignee=people[who] if who is not None else None,
            cycle=cycle if status != "backlog" else None,
            due_date=today + dt.timedelta(days=index - 2) if status not in ("done", "backlog") else None,
        )
        if label:
            issue.labels.add(labels[label])
        issues.append(issue)
    # Finished work spread over the cycle, so the burndown has a shape.
    for offset, issue in zip((5, 2), issues[:2], strict=True):
        Issue.objects.filter(pk=issue.pk).update(completed_at=now - dt.timedelta(days=offset))

    retry = issues[5]
    for position, (text, done) in enumerate([("Agree the retry schedule", True), ("Store the attempt count", False), ("Tests for declined cards", False)], 1):
        ChecklistItem.objects.create(issue=retry, text=text, done=done, position=position, created_by=visitor)
    IssueRelation.objects.create(source=issues[2], target=retry, kind=IssueRelation.Kind.BLOCKS, created_by=people[1])
    issue_type = ContentType.objects.get_for_model(Issue)
    Comment.objects.create(content_type=issue_type, object_id=retry.pk, author=people[1], body="Banks ask for at most **3 retries** a day. I can take the backend part.")
    Comment.objects.create(content_type=issue_type, object_id=issues[4].pk, author=people[2], body="The list is done; paging and the empty state are left.")
    return visitor, workspace
