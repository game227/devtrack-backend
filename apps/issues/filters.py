import django_filters

from .models import Issue


class IssueFilter(django_filters.FilterSet):
    label = django_filters.NumberFilter(field_name="labels__id")
    assignee = django_filters.CharFilter(method="filter_assignee")

    class Meta:
        model = Issue
        fields = ["status", "priority", "type", "assignee", "label", "cycle", "milestone"]

    def filter_assignee(self, queryset, name, value):
        if value == "me":
            return queryset.filter(assignee=self.request.user)
        if not (value.isascii() and value.isdigit()) or int(value) > 2**63 - 1:
            return queryset.none()
        return queryset.filter(assignee_id=int(value))
