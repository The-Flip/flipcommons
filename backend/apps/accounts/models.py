from __future__ import annotations

from typing import Any, ClassVar

from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as BaseUserManager
from django.db import models
from django.db.models.functions import Length, Lower

from apps.actors.models import ActorModel, ActorResolutionStatus
from apps.core.models import field_not_blank

from .usernames import USERNAME_MAX_LEN, USERNAME_MIN_LEN, validate_username_format

# Register the `__length` transform so the `username__length__{gte,lte}`
# lookups in the CheckConstraints below resolve. Django ships Length but
# does NOT auto-register it (since it adds a query-time DB call by default).
# Registering at module load is the documented pattern for using it as a
# lookup transform.
models.CharField.register_lookup(Length)


class UserManager(BaseUserManager["User"]):
    """Custom manager: login is by email; the caller supplies username."""

    use_in_migrations = True

    def get_by_natural_key(self, username: str | None) -> User:
        """Look up a user for password authentication.

        Override of BaseUserManager.get_by_natural_key (exact match) — our
        emails are case-insensitively unique by Lower("email") constraint,
        and admin password login must match that contract or
        Alice@example.com can't log in as alice@example.com.
        """
        return self.get(**{f"{self.model.USERNAME_FIELD}__iexact": username})

    def _create_user(
        self,
        email: str,
        password: str | None,
        **extra_fields: Any,  # noqa: ANN401 - Django manager pattern.
    ) -> User:
        if not email:
            raise ValueError("Email is required.")
        username = extra_fields.get("username")
        if not username:
            # Required at the type level: every write path through the
            # manager (admin add-form, make_user factory, createsuperuser,
            # WorkOS signup-submit) must supply a username. There is no
            # derivation fallback — usernames are user-chosen.
            raise TypeError(
                "username is required; the manager no longer derives it from email."
            )
        # Charset/hyphen rules can't be expressed as a portable CHECK
        # constraint (SQLite has no native REGEXP), so the manager is the
        # chokepoint that enforces them across every write path.
        validate_username_format(username)
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.password = make_password(password)
        user.save(using=self._db)
        return user

    # Signature override is intentional: USERNAME_FIELD = "email", so the
    # first positional is the email (username is supplied via kwargs).
    def create_user(  # type: ignore[override]
        self,
        email: str,
        password: str | None = None,
        **extra_fields: Any,  # noqa: ANN401 - Django manager pattern.
    ) -> User:
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(  # type: ignore[override]
        self,
        email: str,
        password: str | None = None,
        **extra_fields: Any,  # noqa: ANN401 - Django manager pattern.
    ) -> User:
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(ActorModel, AbstractUser):
    # ActorModel is listed first so its save() (Actor mint/sync) is the first
    # in the MRO; it contributes the editable=False ``actor`` OneToOne.
    #
    # AbstractUser provides:
    #   username, first_name, last_name, email,
    #   is_active, is_staff, is_superuser, last_login, date_joined, password
    #
    # `username` is the public URL slug (/users/<username>) and is chosen by
    # the user at signup.

    # Redeclared to tighten max_length from AbstractUser's 150 to our 20,
    # and to wire the format validator into every Django-form-based path
    # (ModelForm/admin, createsuperuser prompts, full_clean callers).
    username = models.CharField(
        max_length=USERNAME_MAX_LEN,
        unique=True,
        validators=[validate_username_format],
    )

    # Redeclared to flip AbstractUser's blank=True to blank=False. Uniqueness
    # is enforced case-insensitively by the Lower("email") UniqueConstraint
    # below; casing is preserved on save (manager only normalizes the domain).
    email = models.EmailField()

    # WorkOS-side user row pointer. null=True only for the soft-delete window:
    # the user.deleted webhook clears this so a returning user can re-bind at
    # reactivation time.
    workos_user_id = models.CharField(max_length=64, null=True, blank=True, unique=True)

    # Mirrored from WorkOS on every login (see _refresh_mirrored_fields).
    # Default False is the safe production posture: a row whose mirror has
    # not yet run is treated as unverified.
    email_verified = models.BooleanField(default=False)

    # Request-time freshness signal (see ProviderSwitching.md).
    last_seen_at = models.DateTimeField(null=True, blank=True)

    # Wikipedia-style attribution priority.
    priority = models.PositiveSmallIntegerField(default=10000)

    # ActorModel contract: a human contributor.
    is_machine: ClassVar[bool] = False

    objects: ClassVar[UserManager] = UserManager()

    USERNAME_FIELD = "email"
    # createsuperuser prompts for REQUIRED_FIELDS, and runs each value
    # through the field's validators — that's where `validate_username_format`
    # earns its keep on the CLI path.
    REQUIRED_FIELDS = ["username"]

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                name="accounts_user_unique_email_ci",
            ),
            field_not_blank("email"),
            field_not_blank("workos_user_id"),
            # Length CHECK only — charset/hyphen rules are app-layer
            # because Django's __regex lookup isn't portable to SQLite
            # CHECK DDL. The format validator on the field covers every
            # write path; this constraint is the cross-backend belt for
            # the bound that VARCHAR(20) already enforces on Postgres.
            models.CheckConstraint(
                condition=models.Q(username__length__gte=USERNAME_MIN_LEN),
                name="accounts_user_username_min_length",
            ),
            models.CheckConstraint(
                condition=models.Q(username__length__lte=USERNAME_MAX_LEN),
                name="accounts_user_username_max_length",
            ),
        ]

    def __str__(self) -> str:
        return self.username or self.email

    # ActorModel hooks: the user's Actor mirrors these. Transitional — they read
    # the legacy ``priority`` column that "Drop dead schema" later removes.
    @property
    def actor_priority(self) -> int:
        return self.priority

    @property
    def actor_resolution_status(self) -> ActorResolutionStatus:
        # Users have no resolution-suppression input in v1.
        return ActorResolutionStatus.ACTIVE
