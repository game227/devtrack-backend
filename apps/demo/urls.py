from django.urls import path

from .views import DemoStartView

urlpatterns = [path("", DemoStartView.as_view(), name="demo-start")]
