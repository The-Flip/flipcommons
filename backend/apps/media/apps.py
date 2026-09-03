from django.apps import AppConfig


class MediaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.media"
    verbose_name = "Media"

    def ready(self) -> None:
        # Registers authz rules and the image-codec system checks at startup.
        from . import authz, checks  # noqa: F401

        _register_heif()


def _register_heif() -> None:
    """Teach Pillow to open HEIC/HEIF files.

    Swallows a missing pillow_heif so the system check can report it:
    ``ready()`` runs before the checks, so raising here would replace an
    actionable message with a startup traceback.
    """
    try:
        from pillow_heif import register_heif_opener
    except ImportError:
        return

    register_heif_opener()
