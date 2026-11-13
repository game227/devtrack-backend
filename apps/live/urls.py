from django.urls import path

from .views import ChangesView

urlpatterns = [path("", ChangesView.as_view(), name="changes")]
