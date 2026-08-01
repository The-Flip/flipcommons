from pathlib import Path

from django.conf import settings
from django.contrib import admin
from django.http import HttpRequest
from django.http.response import HttpResponseBase
from django.urls import URLPattern, URLResolver, path, re_path

from .api import api, public_api

urlpatterns: list[URLPattern | URLResolver] = [
    path("djadmin/", admin.site.urls),
    # Public API first — it's the more specific prefix, and its own OpenAPI doc is
    # the public reference. Must precede the internal "api/" catch-all.
    path("api/public/", public_api.urls),
    path("api/", api.urls),
]

# Serve uploaded media files when Django is the public media origin.
# Storage keys are extensionless (e.g. media/{uuid}/thumb), so Django's
# default static view can't guess Content-Type from the filename. We sniff
# the file's magic bytes to set the correct header.


def _serve_media(
    request: HttpRequest,
    path: str = "",
    document_root: str | None = None,
) -> HttpResponseBase:
    from django.views.static import serve

    from apps.media.storage import sniff_image_content_type

    response = serve(request, path, document_root=document_root)
    if response.get("Content-Type", "").startswith("application/octet-stream"):
        assert document_root is not None
        filepath = Path(document_root) / path
        with open(filepath, "rb") as f:
            head = f.read(16)
        detected = sniff_image_content_type(head)
        if detected:
            response["Content-Type"] = detected
    return response


def _should_serve_local_media() -> bool:
    backend = settings.STORAGES.get("default", {}).get("BACKEND", "")
    return (
        backend == "django.core.files.storage.FileSystemStorage"
        and bool(getattr(settings, "MEDIA_ROOT", None))
        and settings.MEDIA_URL.startswith("/")
    )


if _should_serve_local_media():
    urlpatterns += [
        re_path(
            r"^{}(?P<path>.*)$".format(settings.MEDIA_URL.lstrip("/")),
            _serve_media,
            {"document_root": settings.MEDIA_ROOT},
        ),
    ]
