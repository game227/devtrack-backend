import django_filters

from .models import Issue


class IssueFilter(django_filters.FilterSet):
    label = django_filters.NumberFilter(field_name="labels__id")

    class Meta:
        model = Issue
        fields = ["status", "priority", "type", "assignee", "label"]
