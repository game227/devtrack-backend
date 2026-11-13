from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .avatars import clean_avatar
from .tokens import email_verification_token

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "email_verified",
            "first_name",
            "last_name",
            "avatar",
            "bio",
            "title",
            "date_joined",
        ]
        read_only_fields = ["id", "username", "email", "email_verified", "date_joined"]

    def validate_avatar(self, upload):
        # None clears the avatar; anything else is checked and replaced by a clean re-encoded copy.
        return clean_avatar(upload) if upload else upload


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    password_confirm = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ["username", "email", "password", "password_confirm", "first_name", "last_name"]
        extra_kwargs = {"email": {"required": True, "allow_blank": False}}

    def validate_username(self, value):
        if not value.isascii():
            # Look-alike letters from other scripts (a Cyrillic "а" for a Latin "a") would let someone
            # register a name that reads exactly like a teammate's. Existing accounts are unaffected.
            raise serializers.ValidationError("Usernames may only use English letters, digits and @/./+/-/_.")
        # Django's username is case-sensitive, so "Admin" and "admin" would be two accounts. In an app
        # where people @mention each other that is an impersonation trick: compare case-insensitively.
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("A user with that username already exists.")
        return value

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with that email already exists.")
        return value

    def validate(self, attrs):
        if attrs["password"] != attrs.pop("password_confirm"):
            raise serializers.ValidationError({"password_confirm": "Passwords do not match."})
        # Build an unsaved instance so similarity validators can compare
        # the password against username/email/name.
        user = User(
            username=attrs.get("username", ""),
            email=attrs.get("email", ""),
            first_name=attrs.get("first_name", ""),
            last_name=attrs.get("last_name", ""),
        )
        validate_password(attrs["password"], user=user)
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class LoginSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = UserSerializer(self.user).data
        return data


class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)
    new_password_confirm = serializers.CharField(write_only=True)

    def validate_old_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Old password is incorrect.")
        return value

    def validate(self, attrs):
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError({"new_password_confirm": "Passwords do not match."})
        validate_password(attrs["new_password"], user=self.context["request"].user)
        return attrs

    def save(self):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save()
        return user


class AccountDeleteSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True)

    def validate_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Password is incorrect.")
        return value


class EmailVerificationConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()

    def validate(self, attrs):
        try:
            uid = force_str(urlsafe_base64_decode(attrs["uid"]))
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            raise serializers.ValidationError({"uid": "Invalid user."})

        if not email_verification_token.check_token(user, attrs["token"]):
            raise serializers.ValidationError({"token": "Invalid or expired token."})
        attrs["user"] = user
        return attrs

    def save(self):
        user = self.validated_data["user"]
        user.email_verified = True
        user.save(update_fields=["email_verified"])
        return user


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    # Language of the message that carries the reset link (the UI's current language).
    lang = serializers.ChoiceField(choices=["en", "uz"], required=False, default="en")


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True)
    new_password_confirm = serializers.CharField(write_only=True)

    def validate(self, attrs):
        try:
            uid = force_str(urlsafe_base64_decode(attrs["uid"]))
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            raise serializers.ValidationError({"uid": "Invalid user."})

        if not PasswordResetTokenGenerator().check_token(user, attrs["token"]):
            raise serializers.ValidationError({"token": "Invalid or expired token."})
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError({"new_password_confirm": "Passwords do not match."})
        validate_password(attrs["new_password"], user=user)
        attrs["user"] = user
        return attrs

    def save(self):
        user = self.validated_data["user"]
        user.set_password(self.validated_data["new_password"])
        user.save()
        return user
