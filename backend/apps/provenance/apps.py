from django.apps import AppConfig


class ProvenanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.provenance"
    verbose_name = "Provenance"

    def ready(self) -> None:
        from . import authz  # noqa: F401  # registers authz rules at startup
        from .model_bases import checks  # noqa: F401  # registers system checks
