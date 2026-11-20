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
        # The workspace is fixed when the team is created (the view passes it in); a team can never
        # be moved to another workspace.
        read_only_fields = ["id", "workspace", "created_at"]

    def validate_name(self, value):
        # (workspace, name) is unique. The workspace field is read-only, so DRF no longer derives that
        # check on its own — without it a duplicate would surface as a database error (a 500).
        workspace = self.instance.workspace if self.instance is not None else self.context.get("workspace")
        clashes = Team.objects.filter(workspace=workspace, name=value)
        if self.instance is not None:
            clashes = clashes.exclude(pk=self.instance.pk)
        if workspace is not None and clashes.exists():
            raise serializers.ValidationError("A team with this name already exists in this workspace.")
        return value


class TeamMembershipSerializer(serializers.ModelSerializer):
    user = UserBriefSerializer(read_only=True)

    class Meta:
        model = TeamMembership
        fields = ["id", "user", "joined_at"]
        read_only_fields = ["id", "joined_at"]


class TeamMembershipCreateSerializer(serializers.Serializer):
    username = serializers.CharField()

    def validate_username(self, value):
        # Only people already in the team's workspace can join a team (scoped lookup: no probing of
        # usernames that exist elsewhere).
        team = self.context["team"]
        self._user = User.objects.filter(
            username=value, is_active=True, workspace_memberships__workspace_id=team.workspace_id
        ).first()
        if self._user is None:
            raise serializers.ValidationError("No member of this workspace has that username.")
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
