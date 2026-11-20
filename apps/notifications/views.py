from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import generics, serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import webpush
from .models import Notification, PushSubscription
from .serializers import NotificationSerializer


class NotificationListView(generics.ListAPIView):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            Notification.objects.filter(recipient=self.request.user)
            .select_related("content_type")
        )


class NotificationMarkReadView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
        notification.is_read = True
        notification.save(update_fields=["is_read"])
        return Response(NotificationSerializer(notification).data)


class NotificationMarkAllReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        updated = Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
        return Response({"updated": updated}, status=status.HTTP_200_OK)


class PushSubscriptionSerializer(serializers.Serializer):
    endpoint = serializers.URLField(max_length=1000)
    keys = serializers.DictField(child=serializers.CharField(max_length=200))
    lang = serializers.ChoiceField(choices=["en", "uz", "ru"], required=False, default="en")

    def validate_endpoint(self, value):
        if not webpush.allowed_endpoint(value):
            raise serializers.ValidationError("This push service is not supported.")
        return value

    def validate_keys(self, value):
        if not value.get("p256dh") or not value.get("auth"):
            raise serializers.ValidationError("Both p256dh and auth keys are required.")
        return value


class PushStatusView(APIView):
    """GET: whether Web Push is on, the key browsers subscribe with, and how many of yours exist."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            {
                "enabled": webpush.enabled(),
                "public_key": settings.WEB_PUSH_VAPID_PUBLIC_KEY if webpush.enabled() else "",
                "subscriptions": PushSubscription.objects.filter(user=request.user).count(),
            }
        )


class PushSubscribeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not webpush.enabled():
            return Response({"detail": "Push notifications are not set up on this server."}, status=status.HTTP_409_CONFLICT)
        serializer = PushSubscriptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        # A browser belongs to whoever signed in on it last.
        PushSubscription.objects.update_or_create(
            endpoint=data["endpoint"],
            defaults={"user": request.user, "p256dh": data["keys"]["p256dh"], "auth": data["keys"]["auth"], "lang": data["lang"]},
        )
        stale = PushSubscription.objects.filter(user=request.user).values_list("pk", flat=True)[webpush.MAX_SUBSCRIPTIONS_PER_USER :]
        PushSubscription.objects.filter(pk__in=list(stale)).delete()
        return Response({"detail": "Subscribed."}, status=status.HTTP_201_CREATED)


class PushUnsubscribeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        endpoint = request.data.get("endpoint") if hasattr(request.data, "get") else None
        PushSubscription.objects.filter(user=request.user, endpoint=endpoint or "").delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
