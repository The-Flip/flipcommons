"""The scheme example registry: every scheme's ``SchemeExamples``, by key.

Shared by both harnesses — ``test_examples`` drives the URL tables, and
``test_conformance`` reads each scheme's ``example_identifier`` as its
round-trip seed. Discovers ``<scheme>_examples.py`` modules that export
``EXAMPLES``; adding a production scheme therefore needs a matching example
module, not an edit here. The convention is two-part — example data is a
``_examples``-suffixed, non-``test_`` module — so the harnesses (``test_*``,
including ``test_examples`` itself) are excluded by rule, not by a
hand-maintained list.
"""

from apps.citation.citation_types import SCHEME_SPECS
from apps.citation.citation_types.plugin_discovery import discover_package_exports
from apps.citation.tests import schemes as _schemes_package

from .example_data import SchemeExamples

_EXAMPLES_EXPORT = "EXAMPLES"
_EXAMPLES_SUFFIX = "_examples"


def _discover_scheme_examples() -> dict[str, SchemeExamples]:
    """Import every ``<scheme>_examples`` module, keyed by scheme (suffix stripped)."""
    discovered = discover_package_exports(
        _schemes_package,
        _EXAMPLES_EXPORT,
        SchemeExamples,
        include_module=lambda name: (
            name.endswith(_EXAMPLES_SUFFIX) and not name.startswith("test_")
        ),
    )
    return {
        item.module_name.removesuffix(_EXAMPLES_SUFFIX): item.value
        for item in sorted(discovered, key=lambda item: item.module_name)
    }


SCHEME_EXAMPLES: dict[str, SchemeExamples] = _discover_scheme_examples()

assert SCHEME_EXAMPLES.keys() == set(SCHEME_SPECS), (
    "SCHEME_EXAMPLES must cover exactly the registered schemes; "
    f"missing={sorted(set(SCHEME_SPECS) - SCHEME_EXAMPLES.keys())}, "
    f"unregistered={sorted(SCHEME_EXAMPLES.keys() - set(SCHEME_SPECS))}"
)
