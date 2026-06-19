"""``MarkdownField`` — field-storage class for wikilink markdown content.

This is the storage class only; the wikilink-aware authoring↔storage
conversion helpers live in :mod:`apps.core.markdown.field` (above the
models layer), which re-exports this class so ``from apps.core.markdown
import MarkdownField`` keeps working.
"""

from __future__ import annotations

from typing import Any

from django.db import models
from django.forms import Textarea

from apps.core.models.fields._max_length import _contribute_max_length_check
from apps.core.validators import validate_no_mojibake

DEFAULT_MARKDOWN_MAX_LENGTH = 10_000


class MarkdownField(models.TextField[str, str]):
    """A TextField containing markdown with ``[[<entity-type>:<public-id>]]`` links.

    The system introspects models for MarkdownField instances to:
    - Auto-discover which fields need reference syncing
    - Auto-generate ``{field}_html`` rendered output in API responses

    Includes ``validate_no_mojibake`` as a default validator to reject
    encoding-corrupted text at the model level.

    Auto-contributes a ``CHECK (char_length(field) <= max_length)``
    constraint named ``{app}_{model}_{field}_max_length`` — see
    :func:`~apps.core.models.fields._max_length._contribute_max_length_check`.
    """

    default_validators = [validate_no_mojibake]

    def __init__(
        self,
        *args: Any,  # noqa: ANN401
        max_length: int = DEFAULT_MARKDOWN_MAX_LENGTH,
        **kwargs: Any,  # noqa: ANN401
    ) -> None:
        kwargs["max_length"] = max_length
        super().__init__(*args, **kwargs)

    # Django's migration protocol; see Field.deconstruct.
    def deconstruct(self) -> Any:  # noqa: ANN401
        name, _path, args, kwargs = super().deconstruct()
        return name, "django.db.models.TextField", args, kwargs

    def contribute_to_class(
        self,
        cls: type[models.Model],
        name: str,
        private_only: bool = False,
    ) -> None:
        super().contribute_to_class(cls, name, private_only=private_only)
        _contribute_max_length_check(self, cls, name)

    def formfield(self, **kwargs: Any) -> Any:  # type: ignore[override]  # noqa: ANN401
        # See BoundedTextField.formfield — Django's TextField.formfield()
        # does not propagate max_length, so without this override the
        # admin form would skip length validation and an over-cap value
        # would surface as IntegrityError instead of ValidationError.
        defaults: dict[str, Any] = {
            "max_length": self.max_length,
            "widget": Textarea(attrs={"maxlength": self.max_length}),
        }
        defaults.update(kwargs)
        return super().formfield(**defaults)
