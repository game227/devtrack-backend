from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.workspaces.serializers import UserBriefSerializer

from .models import Team, TeamMembership

User = get_user_model()


class TeamSerializer(serializers.ModelSerializer):
    member_count = serializers.IntegerField(source="memberships.count", read_only=True)

    class Meta:
        model = Team
        fields = ["id", "workspace", "name", "description", "member_count", "created_at"]
        read_only_fields = ["id", "created_at"]


class TeamMembershipSerializer(serializers.ModelSerializer):
    user = UserBriefSerializer(read_only=True)

    class Meta:
        model = TeamMembership
        fields = ["id", "user", "joined_at"]
        read_only_fields = ["id", "joined_at"]


class TeamMembershipCreateSerializer(serializers.Serializer):
    username = serializers.CharField()

    def validate_username(self, value):
        try:
            self._user = User.objects.get(username=value)
        except User.DoesNotExist:
            raise serializers.ValidationError("No user with that username exists.")
        return value

    def validate(self, attrs):
        team = self.context["team"]
        if TeamMembership.objects.filter(team=team, user=self._user).exists():
            raise serializers.ValidationError({"username": "User is already a member of this team."})
        attrs["user"] = self._user
        return attrs

    def save(self):
        team = self.context["team"]
        return TeamMembership.objects.create(team=team, user=self.validated_data["user"])
