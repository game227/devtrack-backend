from django.urls import path

from .views import CycleDetailView, CycleListCreateView

urlpatterns = [
    path("", CycleListCreateView.as_view(), name="cycle-list"),
    path("<int:pk>/", CycleDetailView.as_view(), name="cycle-detail"),
]
