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
