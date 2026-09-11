from django.urls import path

from .views import TeamDetailView, TeamListCreateView, TeamMemberDetailView, TeamMembersView

urlpatterns = [
    path("", TeamListCreateView.as_view(), name="team-list"),
    path("<int:pk>/", TeamDetailView.as_view(), name="team-detail"),
    path("<int:pk>/members/", TeamMembersView.as_view(), name="team-members"),
    path("<int:pk>/members/<int:user_id>/", TeamMemberDetailView.as_view(), name="team-member-detail"),
]
