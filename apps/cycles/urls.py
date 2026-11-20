from django.urls import path

from .views import CycleBurndownView, CycleDetailView, CycleListCreateView

urlpatterns = [
    path("", CycleListCreateView.as_view(), name="cycle-list"),
    path("<int:pk>/", CycleDetailView.as_view(), name="cycle-detail"),
    path("<int:pk>/burndown/", CycleBurndownView.as_view(), name="cycle-burndown"),
]
