from django.urls import path

from .stream import stream_view
from .views import ChangesView, PresenceView, StreamTicketView

urlpatterns = [
    path("", ChangesView.as_view(), name="changes"),
    path("ticket/", StreamTicketView.as_view(), name="changes-ticket"),
    path("stream/", stream_view, name="changes-stream"),
    path("presence/", PresenceView.as_view(), name="presence"),
]
