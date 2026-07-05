"""Convention-based plugin discovery: one export per module in a package.

The single implementation behind both the production scheme registry (schemes
under ``citation_types/schemes`` exporting ``SCHEME``) and the test-side example
registry (``<scheme>_examples`` modules exporting ``EXAMPLES``). Each imports
the package's modules, reads a conventional export and holds it to an expected
type — so the boilerplate lives once and the two registries can't drift.

Framework plumbing, not author surface: a scheme author never imports this; the
registry does. Imports nothing from the package, so it sits at the bottom of the
plugin-package stack.
"""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from pkgutil import iter_modules
from types import ModuleType
from typing import NamedTuple


class DiscoveredExport[T](NamedTuple):
    """A discovered module export: the bare module name and the typed value.

    The module name rides along because a caller may derive a key from it (the
    example registry maps ``youtube_examples`` → ``youtube``); a caller that
    keys off the value itself (the scheme registry sorts by ``spec.key``) just
    ignores it.
    """

    module_name: str
    value: T


def discover_package_exports[T](
    package: ModuleType,
    export_name: str,
    expected_type: type[T],
    *,
    include_module: Callable[[str], bool],
) -> list[DiscoveredExport[T]]:
    """Every *export_name* value in *package*'s selected modules, filesystem order.

    Imports each immediate submodule whose bare name satisfies *include_module*,
    reads its ``export_name`` attribute and requires it to be an
    *expected_type* instance — a selected module missing the export, or
    exporting the wrong type, is an authoring mistake that fails loudly here
    rather than surfacing as a silent gap downstream. Callers sort; discovery
    order follows ``iter_modules``.
    """
    discovered: list[DiscoveredExport[T]] = []
    for module_info in iter_modules(package.__path__):
        if not include_module(module_info.name):
            continue
        module = import_module(f"{package.__name__}.{module_info.name}")
        value = getattr(module, export_name, None)
        if not isinstance(value, expected_type):
            raise AssertionError(
                f"{module.__name__} must export {export_name} as "
                f"{expected_type.__name__}"
            )
        discovered.append(DiscoveredExport(module_info.name, value))
    return discovered
