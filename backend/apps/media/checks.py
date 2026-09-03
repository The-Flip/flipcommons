"""System checks for image codec availability."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, NamedTuple

from django.apps.config import AppConfig
from django.core.checks import CheckMessage, Error, Tags, register

from .processing import check_codec_support


class _Codec(NamedTuple):
    """A required decoder, and how to report it missing."""

    key: str  # lookup key into check_codec_support()
    label: str
    extensions: str
    hint: str
    check_id: str


_REQUIRED_CODECS: tuple[_Codec, ...] = (
    _Codec(
        key="heic",
        label="HEIF",
        extensions=".heic/.heif",
        hint=(
            "pillow-heif is a declared dependency, so a missing module means "
            "the environment is out of sync with uv.lock. Run "
            "`cd backend && uv sync`."
        ),
        check_id="media.E001",
    ),
    _Codec(
        key="avif",
        label="AVIF",
        extensions=".avif",
        hint=(
            "Pillow must be built against libavif. The manylinux and macOS "
            "wheels bundle it, so a source build or a trimmed base image is "
            "the usual cause."
        ),
        check_id="media.E002",
    ),
)


@register(Tags.compatibility)
def check_image_codecs(
    app_configs: Sequence[AppConfig] | None,
    **kwargs: Any,  # noqa: ANN401
) -> list[CheckMessage]:
    """Error when a codec behind an accepted upload extension is missing."""
    _ = app_configs, kwargs
    support = check_codec_support()
    return [
        Error(
            f"{codec.label} support is unavailable. The upload endpoint "
            f"accepts {codec.extensions} but will reject every such file "
            f"with a 400.",
            hint=codec.hint,
            id=codec.check_id,
        )
        for codec in _REQUIRED_CODECS
        if not support.get(codec.key)
    ]
