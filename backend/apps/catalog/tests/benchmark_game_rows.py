"""Benchmark the card-grain roll-up engine — the proving harness behind the
figures in docs/plans/filtering_and_search/ModelFilteringPlan.md.

Prints the no-filter listing page, the manufacturer facet at card grain and
the full facet fan-out, against whatever database ``DATABASE_URL`` points at.
Run it against the Docker Postgres for performance and against SQLite for
feasibility (from ``backend/``):

    DATABASE_URL='postgresql://postgres:dev@127.0.0.1:5433/postgres' \\  # pragma: allowlist secret
        uv run python -m apps.catalog.tests.benchmark_game_rows

Lives under ``tests/`` (unprefixed, so pytest never collects it) because it is
measurement tooling over the api layer: a management command may not import
``apps.catalog.api`` (the api/admin/management layers are independent entry
surfaces), while the tests layer is exempt from the app's layer contract.

The yardstick (ModelFilteringPlan.md → COMMIT.HET.PROVE): the manufacturer
facet's documented Postgres profile is ~11 ms for the ordered-scan rollup that
serves today's Title-grain badge, against ~280 ms for the correlated-subquery
shape it replaced. Card counts have to come in at the former order. The
baseline section times today's Title-grain paths on the same database so the
comparison never leans on a stale number.

Also prints the correctness counts the plan predicts from ``mf_card_counts``
so a regression is visible next to its timing.
"""

from __future__ import annotations

import argparse
import statistics
import time
from collections.abc import Callable
from functools import partial


def main() -> None:
    from django.db import connection

    from apps.catalog.api._game_facets import game_facet_counts
    from apps.catalog.api._game_rows import GameFilters, game_rows_merged
    from apps.catalog.api._title_facets import (
        TitleFilters,
        _count_manufacturer,
        _expand_taxonomy,
        _facet_base,
        ordered_titles,
    )
    from apps.catalog.engine.query.constants import DEFAULT_PAGE_SIZE

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runs",
        type=int,
        default=5,
        help="Timed runs per case (after one warmup); the median is reported.",
    )
    runs = parser.parse_args().runs

    # (label, filters, the value mf_card_counts predicted at patch
    # 0188-model-lineage) — re-run the analysis file rather than editing these
    # numbers by hand.
    correctness: tuple[tuple[str, GameFilters, int], ...] = (
        ("no filter", GameFilters(), 6180),
        ("manufacturer=vifico", GameFilters(manufacturer="vifico"), 13),
        (
            "manufacturer=chicago-gaming",
            GameFilters(manufacturer="chicago-gaming"),
            15,
        ),
        ("manufacturer=williams", GameFilters(manufacturer="williams"), 487),
        ("tech_gen=solid-state", GameFilters(tech_gen="solid-state"), 1432),
        ("theme=fantasy", GameFilters(themes=("fantasy",)), 396),
        ("q=godzilla", GameFilters(q="godzilla"), 3),
    )

    # The filtered fan-out cases — pinned so the third figure is reproducible.
    fanout_filters: tuple[tuple[str, GameFilters], ...] = (
        ("no filter", GameFilters()),
        ("tech_gen=solid-state", GameFilters(tech_gen="solid-state")),
        ("manufacturer=williams", GameFilters(manufacturer="williams")),
    )

    def page_merged(f: GameFilters) -> int:
        """What the list endpoint does per request: build the rows (the count
        is the list's length), slice page 1."""
        rows = game_rows_merged(f)
        rows[:DEFAULT_PAGE_SIZE]
        return len(rows)

    def baseline_listing_page() -> int:
        """Today's no-filter listing page: ordered Titles, page 1 + count."""
        qs = ordered_titles(TitleFilters())
        list(qs[:DEFAULT_PAGE_SIZE])
        return qs.count()

    def baseline_manufacturer_facet() -> int:
        """Today's Title-grain manufacturer facet count (the documented ~11 ms
        ordered-scan rollup), on the same database as the card-grain figures."""
        f = TitleFilters()
        expansion = _expand_taxonomy(f)
        return len(_count_manufacturer(_facet_base(f, "manufacturer", expansion)))

    def timed[T](fn: Callable[[], T]) -> tuple[float, T]:
        """Median wall-clock ms over *runs* (one discarded warmup)."""
        result = fn()
        samples = []
        for _ in range(runs):
            t0 = time.perf_counter()
            fn()
            samples.append((time.perf_counter() - t0) * 1000)
        return statistics.median(samples), result

    print(f"vendor: {connection.vendor}   runs: {runs} (median, 1 warmup)\n")

    print("== correctness — listing count ==")
    for label, f, expected in correctness:
        got = len(game_rows_merged(f))
        mark = "ok" if got == expected else f"MISMATCH (expected {expected})"
        print(f"  {label:32s} {got:6d}  {mark}")

    print("\n== baseline — today's Title-grain paths, same database ==")
    ms, _ = timed(baseline_listing_page)
    print(f"  no-filter listing page (ordered_titles)      {ms:8.1f} ms")
    ms, _ = timed(baseline_manufacturer_facet)
    print(f"  no-filter manufacturer facet (Title grain)   {ms:8.1f} ms")

    print("\n== listing page (page 1 + count) ==")
    for label, f in fanout_filters:
        ms, _ = timed(partial(page_merged, f))
        print(f"  {label:24s} {ms:8.1f} ms")

    # The badge sum mf_card_counts predicts for the no-filter manufacturer
    # facet — a correctness check beside the timing. The filtered cases carry
    # no prediction, so their sums print uncompared.
    expected_badge_sum = {"no filter": 6147}
    print("\n== facet fan-out at card grain (all dimensions) ==")
    for label, f in fanout_filters:
        ms, opts = timed(partial(game_facet_counts, f))
        badge_sum = sum(o.count for o in opts.manufacturer)
        expected_sum = expected_badge_sum.get(label)
        mark = (
            ""
            if expected_sum is None
            else (
                " ok"
                if badge_sum == expected_sum
                else f"  MISMATCH (expected {expected_sum})"
            )
        )
        print(
            f"  {label:24s} {ms:8.1f} ms  "
            f"(manufacturer: {len(opts.manufacturer)} values, sum {badge_sum}){mark}"
        )


if __name__ == "__main__":
    import os

    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()
    main()
