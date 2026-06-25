from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"

    def ready(self) -> None:
        # Patch AnonymousUser with the attributes the PolicyUser Protocol
        # declares but Django's AnonymousUser lacks, so anonymous requests
        # structurally satisfy PolicyUser without forking django-stubs. The
        # contract is asserted in test_authz_predicates so a missing patch
        # fails loud.
        #   * email_verified: launch-gate predicate reads it.
        #   * actor_id: is_changeset_author compares it to a changeset's
        #     actor_id; None for anonymous (an anon caller owns no changeset),
        #     mirroring how AnonymousUser.id is None.
        from django.contrib.auth.models import AnonymousUser

        AnonymousUser.email_verified = False  # type: ignore[attr-defined]
        AnonymousUser.actor_id = None  # type: ignore[attr-defined]
