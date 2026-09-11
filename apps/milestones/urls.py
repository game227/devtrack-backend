from django.urls import path

from .views import MilestoneDetailView, MilestoneListCreateView

urlpatterns = [
    path("", MilestoneListCreateView.as_view(), name="milestone-list"),
    path("<int:pk>/", MilestoneDetailView.as_view(), name="milestone-detail"),
]
