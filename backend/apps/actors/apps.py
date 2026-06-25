from django.apps import AppConfig


class ActorsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.actors"
    label = "actors"
    verbose_name = "Actors"

    def ready(self) -> None:
        # Import for side effects: registers the class-shape system check
        # (DB-free; validates the ActorModel registry, not Actor rows).
        from . import checks  # noqa: F401

        # Wire the pre_delete guard that protects backing records whose Actor
        # has attributed history (replaces the dropped per-type PROTECT FKs).
        from .models.base import connect_delete_guards

        connect_delete_guards()
