from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework import serializers

from .models import Invitation, Membership, Workspace

User = get_user_model()


class UserBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "avatar"]


class WorkspaceSerializer(serializers.ModelSerializer):
    owner = UserBriefSerializer(read_only=True)
    my_role = serializers.SerializerMethodField()

    class Meta:
        model = Workspace
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "owner",
            "is_personal",
            "my_role",
            "created_at",
        ]
        read_only_fields = ["id", "slug", "owner", "is_personal", "created_at"]

    def get_my_role(self, obj):
        request = self.context.get("request")
        if request is None:
            return None
        membership = obj.memberships.filter(user=request.user).first()
        return membership.role if membership else None


class MembershipSerializer(serializers.ModelSerializer):
    user = UserBriefSerializer(read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "user", "role", "joined_at"]
        read_only_fields = ["id", "joined_at"]


class MembershipCreateSerializer(serializers.Serializer):
    username = serializers.CharField()
    role = serializers.ChoiceField(
        choices=[Membership.Role.ADMIN, Membership.Role.MEMBER], default=Membership.Role.MEMBER
    )

    def validate_username(self, value):
        try:
            self._user = User.objects.get(username=value, is_active=True)
        except User.DoesNotExist:
            raise serializers.ValidationError("No user with that username exists.")
        return value

    def validate(self, attrs):
        workspace = self.context["workspace"]
        if Membership.objects.filter(workspace=workspace, user=self._user).exists():
            raise serializers.ValidationError({"username": "User is already a member of this workspace."})
        if Invitation.objects.valid().filter(workspace=workspace, user=self._user).exists():
            raise serializers.ValidationError({"username": "User has already been invited to this workspace."})
        attrs["user"] = self._user
        return attrs

    def save(self):
        workspace, user = self.context["workspace"], self.validated_data["user"]
        try:
            with transaction.atomic():
                # An expired or orphaned earlier invitation is replaced by this one.
                Invitation.objects.filter(workspace=workspace, user=user).delete()
                return Invitation.objects.create(
                    workspace=workspace,
                    user=user,
                    invited_by=self.context["invited_by"],
                    role=self.validated_data["role"],
                )
        except IntegrityError as exc:
            # Two admins invited the same person at the same moment.
            raise serializers.ValidationError({"username": "User has already been invited to this workspace."}) from exc


class WorkspaceBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Workspace
        fields = ["id", "name"]


class InvitationSerializer(serializers.ModelSerializer):
    workspace = WorkspaceBriefSerializer(read_only=True)
    user = UserBriefSerializer(read_only=True)
    invited_by = UserBriefSerializer(read_only=True)

    class Meta:
        model = Invitation
        fields = ["id", "workspace", "user", "invited_by", "role", "created_at"]
        read_only_fields = fields
