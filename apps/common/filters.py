from django.db.models import F
from rest_framework.filters import OrderingFilter


class StableOrderingFilter(OrderingFilter):
    """DRF's OrderingFilter, made safe to page through.

    Rows with the same value (or no value) for the chosen field would otherwise come back in whatever
    order PostgreSQL likes on each page query, so a client could see an item twice and miss another.
    Empty values always sort last, and ties are broken by id.
    """

    def filter_queryset(self, request, queryset, view):
        ordering = self.get_ordering(request, queryset, view)
        if not ordering:
            return queryset
        terms = [
            F(field[1:]).desc(nulls_last=True) if field.startswith("-") else F(field).asc(nulls_last=True)
            for field in ordering
        ]
        return queryset.order_by(*terms, "-id")
