import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone as dj_timezone

# E.164 international format, e.g. +919876543210 (India +91 is the default market)
phone_validator = RegexValidator(r"^\+[1-9]\d{7,14}$", "Enter the number in international format, e.g. +919876543210.")


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("Email is required.")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.update(is_staff=True, is_superuser=True)
        return self.create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    """Global identity. Company membership and roles are separate (tenancy app, Phase 1)."""

    ONLINE, AWAY, OFFLINE = "online", "away", "offline"
    AVAILABILITY = [(ONLINE, "Online"), (AWAY, "Away"), (OFFLINE, "Offline")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=16, blank=True, validators=[phone_validator])
    avatar = models.ImageField(upload_to="avatars/", blank=True)
    timezone = models.CharField(max_length=50, blank=True, help_text="Empty = platform default")
    notification_prefs = models.JSONField(default=dict, blank=True)
    availability = models.CharField(
        max_length=10, choices=AVAILABILITY, default=OFFLINE, help_text="Used for human handoff routing"
    )
    platform_role = models.ForeignKey(
        "rbac.Role",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        limit_choices_to={"scope": "platform"},
        related_name="staff",
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False, help_text="Platform staff (Super Admin / Support).")
    date_joined = models.DateTimeField(default=dj_timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.email
