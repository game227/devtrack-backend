"""
URL configuration for the DevTrack backend.
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

from apps.analytics.views import DashboardView
from apps.projects.views import NoteDetailView


def health(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/health/", health),
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/workspaces/", include("apps.workspaces.urls")),
    path("api/v1/projects/", include("apps.projects.urls")),
    path("api/v1/labels/", include("apps.projects.label_urls")),
    path("api/v1/notes/<int:pk>/", NoteDetailView.as_view(), name="note-detail"),
    path("api/v1/issues/", include("apps.issues.urls")),
    path("api/v1/comments/", include("apps.comments.urls")),
    path("api/v1/activities/", include("apps.activities.urls")),
    path("api/v1/dashboard/", DashboardView.as_view(), name="dashboard"),
    path("api/v1/analytics/", include("apps.analytics.urls")),
    path("api/v1/teams/", include("apps.teams.urls")),
    path("api/v1/cycles/", include("apps.cycles.urls")),
    path("api/v1/milestones/", include("apps.milestones.urls")),
    path("api/v1/notifications/", include("apps.notifications.urls")),
    path("api/v1/integrations/", include("apps.integrations.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
