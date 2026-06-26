"""Find module-level dead code and code kept alive only by tests.

Vulture treats a reference from a test as a use, so in a highly-tested codebase
it goes quiet exactly where rot hides. This command answers the harder question
using grimp (the static import graph that backs import-linter):

  * DEAD       — modules nothing imports at all (not prod, not tests).
  * TEST-ONLY  — production modules reachable *only* through test code. These are
                 kept alive solely by their tests; deleting the code and its test
                 together is usually safe.

It is module-granularity and static-only (see caveats below), so treat the
output as a triage list, not a delete list.

Seeding
-------
Django loads many modules by string/convention (INSTALLED_APPS, signal
autodiscovery, the ``{app}.api`` router autodiscovery, string-referenced
middleware), which the static graph can't see. Because this is a management
command, Django is fully booted, so we seed the production entrypoint set from
the live app registry and settings rather than guessing — then walk the import
graph upstream from those seeds to get everything genuinely reachable in prod.

Caveats
-------
* Module-granularity: a module can be reachable in prod yet still contain a dead
  *function*. For function-level "alive only by tests", use coverage over a
  production run, not pytest.
* Static-only: a module reached purely via ``importlib``/string from app code
  (not a known Django convention) will look dead. Eyeball before deleting.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import grimp
from django.apps import apps as django_apps
from django.conf import settings
from django.core.management.base import BaseCommand

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.core.management.base import CommandParser

# Top-level packages whose modules we judge. Everything else (Django, ninja,
# stdlib) is an external boundary we don't report on.
FIRST_PARTY_PACKAGES = ("apps", "config")

# Per-app modules Django loads by convention regardless of who imports them.
# `{app}.api` is this project's router-autodiscovery convention (config.api).
_APP_CONVENTION_SUFFIXES = (
    "apps",  # AppConfig + ready() hooks
    "models",  # loaded during app population
    "admin",  # admin autodiscovery
    "api",  # router autodiscovery (config.api._discover_routers)
    "signals",  # imported from ready() by convention
)


def _module_exists_in_graph(graph: grimp.ImportGraph, name: str) -> bool:
    return name in graph.modules


def _is_test_module(name: str) -> bool:
    """A module that exists to test, not to run in production."""
    parts = name.split(".")
    return (
        "tests" in parts
        or parts[-1] == "conftest"
        or parts[-1].startswith("test_")
        or parts[-1] == "test_factories"
        or parts[-1].endswith("_test_factories")
    )


def _is_migration(name: str) -> bool:
    return "migrations" in name.split(".")


class Command(BaseCommand):
    help = "Find dead modules and modules kept alive only by tests (via grimp)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="For each test-only module, print a shortest import chain from a test.",
        )
        parser.add_argument(
            "--include-migrations",
            action="store_true",
            help="Don't filter migration modules out of the report (noisy).",
        )

    def handle(
        self,
        *args: object,
        verbose: bool = False,
        include_migrations: bool = False,
        **opts: object,
    ) -> None:
        graph = grimp.build_graph(*FIRST_PARTY_PACKAGES)

        prod_seeds = self._production_seeds(graph)
        test_seeds = {m for m in graph.modules if _is_test_module(m)}

        prod_reachable = self._closure(graph, prod_seeds)
        test_reachable = self._closure(graph, test_seeds)

        all_modules = set(graph.modules)
        # Package __init__ modules (anything with children in the graph) are
        # structural, not code — drop them to cut noise.
        packages = {m for m in all_modules if graph.find_children(m)}
        candidates = all_modules - packages - test_seeds
        if not include_migrations:
            candidates = {m for m in candidates if not _is_migration(m)}

        dead = sorted(candidates - prod_reachable - test_reachable)
        test_only = sorted((candidates & test_reachable) - prod_reachable)

        self._report("DEAD — imported by nothing (prod or tests)", dead)
        self._report("TEST-ONLY — production modules reached only via tests", test_only)

        if verbose and test_only:
            self.stdout.write("\nShortest import chain from a test entrypoint:")
            for module in test_only:
                chain = self._chain_from(graph, test_seeds, module)
                pretty = " -> ".join(chain) if chain else "(no direct chain found)"
                self.stdout.write(f"  {module}\n    {pretty}")

        self.stdout.write(
            self.style.NOTICE(
                f"\n{len(dead)} dead, {len(test_only)} test-only "
                f"(of {len(candidates)} candidate modules). "
                "Module-granularity, static-only — triage before deleting."
            )
        )

    def _production_seeds(self, graph: grimp.ImportGraph) -> set[str]:
        """Entrypoints Django reaches without an app-level static import."""
        seeds: set[str] = set()

        def keep(name: str) -> None:
            if _module_exists_in_graph(graph, name):
                seeds.add(name)

        # Per-app convention modules, straight from the live registry. `keep`
        # filters to the graph, so non-first-party apps fall away on their own.
        for app_config in django_apps.get_app_configs():
            # The AppConfig's own module — when INSTALLED_APPS names the config
            # class by dotted path (e.g. "apps.core.admin_apps.FlipAdminConfig")
            # it lives outside the `{app}.apps` convention. Note `name` can be
            # first-party-disjoint (FlipAdminConfig.name == "django.contrib.admin")
            # even though its module is first-party — so seed it unconditionally.
            keep(type(app_config).__module__)
            # AdminConfig.default_site points at a string-loaded AdminSite module.
            default_site = getattr(app_config, "default_site", None)
            if isinstance(default_site, str):
                keep(default_site.rsplit(".", 1)[0])

            base = app_config.name
            if not base.startswith(FIRST_PARTY_PACKAGES):
                continue
            for suffix in _APP_CONVENTION_SUFFIXES:
                keep(f"{base}.{suffix}")
            # Management commands are invoked by name, never imported by app code.
            for command_module in graph.find_descendants(base):
                if ".management.commands." in command_module + ".":
                    keep(command_module)

        # Config-level wiring referenced by string in settings.
        keep(getattr(settings, "ROOT_URLCONF", "config.urls"))
        for dotted in ("config.api", "config.asgi", "config.wsgi", "config.settings"):
            keep(dotted)
        wsgi_app = getattr(settings, "WSGI_APPLICATION", None)
        if wsgi_app:
            keep(wsgi_app.rsplit(".", 1)[0])

        # Dotted-path class strings Django imports from settings: middleware and
        # auth backends. Seed the module each lives in.
        string_loaded = (
            *getattr(settings, "MIDDLEWARE", ()),
            *getattr(settings, "AUTHENTICATION_BACKENDS", ()),
        )
        for dotted in string_loaded:
            module = dotted.rsplit(".", 1)[0]
            if module.startswith(FIRST_PARTY_PACKAGES):
                keep(module)

        return seeds

    @staticmethod
    def _closure(graph: grimp.ImportGraph, seeds: Iterable[str]) -> set[str]:
        """Seeds plus everything they import, transitively."""
        reached: set[str] = set()
        for seed in seeds:
            reached.add(seed)
            reached |= graph.find_upstream_modules(seed)
        return reached

    @staticmethod
    def _chain_from(
        graph: grimp.ImportGraph, seeds: Iterable[str], target: str
    ) -> tuple[str, ...] | None:
        chains = (graph.find_shortest_chain(seed, target) for seed in seeds)
        found = [c for c in chains if c]
        return min(found, key=len) if found else None

    def _report(self, title: str, modules: list[str]) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{title} ({len(modules)})"))
        if not modules:
            self.stdout.write("  (none)")
            return
        for module in modules:
            self.stdout.write(f"  {module}")
