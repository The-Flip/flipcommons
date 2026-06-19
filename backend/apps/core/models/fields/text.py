"""``BoundedTextField`` — a ``TextField`` with an auto-contributed length CHECK."""

from __future__ import annotations

from typing import Any

from django.db import models
from django.forms import Textarea

from apps.core.models.fields._max_length import _contribute_max_length_check


class BoundedTextField(models.TextField[str, str]):
    """A ``TextField`` that auto-contributes a length CHECK constraint.

    Use for prose fields where the cap is a sanity bound, not part of the
    data's identity (where ``CharField`` would be more idiomatic). The
    field stores as ``TEXT`` in Postgres; the cap is enforced by a
    generated ``CHECK (char_length(field) <= max_length)`` constraint
    named ``{app}_{model}_{field}_max_length``.

    ``max_length`` is required. ``__length`` compiles to Postgres
    ``char_length()`` so the cap counts characters, not bytes.
    """

    def __init__(self, *args: Any, max_length: int, **kwargs: Any) -> None:  # noqa: ANN401
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
        # Django's TextField.formfield() does not propagate max_length to
        # the form field — without this override, admin form validation
        # would skip the length check and let an over-cap value through
        # to the DB, where it would surface as IntegrityError instead of
        # ValidationError. Also attach a browser-side maxlength hint.
        defaults: dict[str, Any] = {
            "max_length": self.max_length,
            "widget": Textarea(attrs={"maxlength": self.max_length}),
        }
        defaults.update(kwargs)
        return super().formfield(**defaults)
