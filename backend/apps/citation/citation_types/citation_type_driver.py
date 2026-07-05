"""The citation-type framework: the driver for citation type specs.

**Framework-facing only** — a type author never imports this module; an
import-linter contract fails the build if a plugin module tries. The type
axis's counterpart to ``citation_scheme_driver``: where a scheme driver
compiles and runs pure configuration, :class:`CitationTypeDriver` runs the
*declared programming* of a type — the ``LocatorContract`` callables its
module wrote — behind one uniform surface, so no consumer calls a contract
field directly or re-implements the None-guards around the optional value
bridge.

The registry constructs one driver per registered type; the registry's
weaves, the locator write-path validation (``locators.py``) and recognition
hint formatting all run through it.
"""

from __future__ import annotations

from apps.citation.citation_types.citation_type_specs import CitationTypeSpec
from apps.citation.citation_types.vocabulary import StartSeconds


class CitationTypeDriver:
    """Drives one citation type spec: the locator grammar behind one surface.

    Every method is a total function over the type's declared contract — the
    optional value bridge (``parse_value``/``format_value``) is None-guarded
    here, once, so consumers never branch on contract fields.
    """

    def __init__(self, spec: CitationTypeSpec) -> None:
        self.spec = spec

    def normalize_locator(self, locator: str) -> str | None:
        """Validate + canonicalize non-empty locator text, ``None`` if invalid."""
        return self.spec.locator.normalize(locator)

    def parse_locator_value(self, text: str) -> StartSeconds | None:
        """Parse value text through the type's grammar, or ``None``.

        ``None`` both when the type has no structured value (freeform types)
        and when *text* doesn't parse — either way, there is no value.
        """
        parse_value = self.spec.locator.parse_value
        if parse_value is None:
            return None
        return parse_value(text)

    def format_locator_value(self, value: StartSeconds) -> str | None:
        """Format the type's structured value as locator text, or ``None``.

        ``None`` when the type has no structured value to format.
        """
        format_value = self.spec.locator.format_value
        if format_value is None:
            return None
        return format_value(value)
