from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Membership, Workspace

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
            self._user = User.objects.get(username=value)
        except User.DoesNotExist:
            raise serializers.ValidationError("No user with that username exists.")
        return value

    def validate(self, attrs):
        workspace = self.context["workspace"]
        if Membership.objects.filter(workspace=workspace, user=self._user).exists():
            raise serializers.ValidationError({"username": "User is already a member of this workspace."})
        attrs["user"] = self._user
        return attrs

    def save(self):
        workspace = self.context["workspace"]
        return Membership.objects.create(
            workspace=workspace, user=self.validated_data["user"], role=self.validated_data["role"]
        )
