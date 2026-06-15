"""The ORM-free winner-pick agrees with the SQL annotation, claim for claim.

:mod:`apps.catalog.resolve.claim_ranking_in_memory` re-expresses the ranking
that :func:`apps.provenance.claim_ranking_in_db.ranked_claims` performs in SQL.
The two must pick the *same* winner for every ``claim_key`` or the patch front end's
post-state model would silently diverge from what the bulk resolver writes.
``TestSqlEquivalence`` is that contract — including the exact-tie cases (equal
priority + ``created_at``) that the ``-pk`` tiebreak makes deterministic; the
pure-unit tests below pin the edges (priority, recency, pk, eligibility,
pending) without a database.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from django.contrib.auth import get_user_model

from apps.catalog.resolve import resolve_all_entities, resolve_model
from apps.catalog.resolve.claim_ranking_in_memory import (
    effective_priority,
    is_eligible,
    pick_winners,
    winner_sort_key,
)
from apps.catalog.tests.conftest import make_machine_model
from apps.provenance.claim_ranking_in_db import ranked_claims
from apps.provenance.models import Claim, ClaimControlledModel, Source

# --------------------------------------------------------------------------
# Pure-unit tests (no database) — pin the definition's edges.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Src:
    priority: int
    is_enabled: bool = True


@dataclass(frozen=True)
class _Usr:
    priority: int


@dataclass(frozen=True)
class _FakeClaim:
    claim_key: str
    is_active: bool = True
    created_at: datetime | None = None
    pk: int | None = None  # None ⟺ pending (pairs with created_at=None)
    source: _Src | None = None
    user: _Usr | None = None


_T0 = datetime(2024, 1, 1, tzinfo=UTC)


class TestEligibility:
    def test_inactive_claim_excluded(self) -> None:
        assert not is_eligible(_FakeClaim("name", is_active=False, source=_Src(10)))

    def test_disabled_source_excluded(self) -> None:
        assert not is_eligible(_FakeClaim("name", source=_Src(99, is_enabled=False)))

    def test_active_enabled_source_included(self) -> None:
        assert is_eligible(_FakeClaim("name", source=_Src(10)))

    def test_active_user_claim_included(self) -> None:
        # No source: the source-enabled check must not drop it.
        assert is_eligible(_FakeClaim("name", user=_Usr(10)))


class TestEffectivePriority:
    def test_source_priority(self) -> None:
        assert effective_priority(_FakeClaim("name", source=_Src(20))) == 20

    def test_user_priority_when_no_source(self) -> None:
        assert effective_priority(_FakeClaim("name", user=_Usr(7))) == 7

    def test_zero_when_neither(self) -> None:
        assert effective_priority(_FakeClaim("name")) == 0


class TestPickWinners:
    def test_higher_priority_wins(self) -> None:
        lo = _FakeClaim("year", created_at=_T0, pk=1, source=_Src(10))
        hi = _FakeClaim("year", created_at=_T0, pk=2, source=_Src(20))
        assert pick_winners([lo, hi])["year"] is hi

    def test_same_priority_newest_wins(self) -> None:
        older = _FakeClaim("name", created_at=_T0, pk=1, source=_Src(10))
        newer = _FakeClaim(
            "name", created_at=_T0 + timedelta(days=1), pk=2, source=_Src(10)
        )
        assert pick_winners([older, newer])["name"] is newer

    def test_exact_tie_breaks_by_highest_pk(self) -> None:
        # Same priority and created_at: the pk tiebreak decides (highest = last
        # write), so the result is total and independent of input order.
        lo_pk = _FakeClaim("name", created_at=_T0, pk=1, source=_Src(10))
        hi_pk = _FakeClaim("name", created_at=_T0, pk=2, source=_Src(10))
        assert pick_winners([lo_pk, hi_pk])["name"] is hi_pk
        assert pick_winners([hi_pk, lo_pk])["name"] is hi_pk  # order must not matter

    def test_pending_sorts_as_newest(self) -> None:
        # created_at=None is a pending claim — it outranks any committed claim
        # at equal priority (winner_sort_key recency is the +inf sentinel).
        committed = _FakeClaim("name", created_at=_T0, pk=1, source=_Src(10))
        pending = _FakeClaim("name", created_at=None, source=_Src(10))
        assert pick_winners([committed, pending])["name"] is pending
        assert winner_sort_key(pending) > winner_sort_key(committed)

    def test_pending_still_loses_to_higher_priority(self) -> None:
        # Recency only breaks ties — a higher-priority committed claim beats
        # a lower-priority pending one.  (The headline reassign-then-delete
        # validation property in the plan doc.)
        committed_hi = _FakeClaim("name", created_at=_T0, pk=1, source=_Src(20))
        pending_lo = _FakeClaim("name", created_at=None, source=_Src(10))
        assert pick_winners([committed_hi, pending_lo])["name"] is committed_hi

    def test_ineligible_dropped_before_pick(self) -> None:
        disabled_hi = _FakeClaim(
            "name", created_at=_T0, pk=1, source=_Src(99, is_enabled=False)
        )
        enabled_lo = _FakeClaim("name", created_at=_T0, pk=2, source=_Src(1))
        assert pick_winners([disabled_hi, enabled_lo])["name"] is enabled_lo

    def test_groups_by_claim_key(self) -> None:
        name = _FakeClaim("name", created_at=_T0, pk=1, source=_Src(10))
        year = _FakeClaim("year", created_at=_T0, pk=2, source=_Src(10))
        winners = pick_winners([name, year])
        assert winners == {"name": name, "year": year}


# --------------------------------------------------------------------------
# Equivalence test (database) — the SQL form and the pure form must agree.
# --------------------------------------------------------------------------


def _sql_winners(subject: ClaimControlledModel) -> dict[str, Claim]:
    """Winners the resolvers would pick, via the shared ``ranked_claims``.

    Calls the same SQL winner-pick every production resolver uses, so this
    mirror cannot drift from what they actually do.
    """
    claims = ranked_claims(subject.claims.all(), "claim_key")
    winners: dict[str, Claim] = {}
    for claim in claims:
        winners.setdefault(claim.claim_key, claim)
    return winners


def _set_created_at(claim: Claim, when: datetime) -> None:
    """Pin a claim's auto_now_add created_at to a deterministic value."""
    Claim.objects.filter(pk=claim.pk).update(created_at=when)


class TestSqlEquivalence:
    @pytest.fixture
    def sources(self, db: object) -> dict[str, Source]:
        return {
            "ipdb": Source.objects.create(
                name="IPDB", source_type="database", priority=10
            ),
            # A second enabled source at the SAME priority as ipdb, for exact-tie
            # cases (equal priority + created_at, decided only by pk).
            "ipdb_b": Source.objects.create(
                name="IPDB Mirror", source_type="database", priority=10
            ),
            "opdb": Source.objects.create(
                name="OPDB", source_type="database", priority=20
            ),
            "editorial": Source.objects.create(
                name="Editorial", source_type="editorial", priority=100
            ),
            "disabled": Source.objects.create(
                name="Disabled", source_type="other", priority=999, is_enabled=False
            ),
        }

    def _assert_agree(self, subject: ClaimControlledModel) -> None:
        sql = _sql_winners(subject)
        claims = list(subject.claims.select_related("source", "user").all())
        pure = pick_winners(claims)
        assert {k: v.pk for k, v in sql.items()} == {k: v.pk for k, v in pure.items()}

    def test_priority_recency_disabled_and_inactive(
        self, sources: dict[str, Source]
    ) -> None:
        pm = make_machine_model(name="Equiv Pin", slug="equiv-pin")

        # year: higher priority wins over lower.
        lo = Claim.objects.assert_claim(pm, "year", 1996, source=sources["ipdb"])
        hi = Claim.objects.assert_claim(pm, "year", 1997, source=sources["opdb"])
        _set_created_at(lo, _T0)
        _set_created_at(hi, _T0 - timedelta(days=5))  # older but higher priority

        # name: equal priority, newest created_at wins.
        old_name = Claim.objects.assert_claim(
            pm, "name", "Old", source=sources["editorial"]
        )
        new_name = Claim.objects.assert_claim(
            pm, "name", "New", source=sources["editorial"]
        )
        _set_created_at(old_name, _T0)
        _set_created_at(new_name, _T0 + timedelta(days=1))

        # year also claimed by a disabled (highest-priority) source — both
        # forms must ignore it, leaving opdb's 1997 the winner.
        Claim.objects.assert_claim(pm, "year", 2099, source=sources["disabled"])

        self._assert_agree(pm)

    def test_user_versus_source(self, sources: dict[str, Source]) -> None:
        user = get_user_model().objects.create(
            email="ranker@example.com", username="ranker", priority=50
        )
        pm = make_machine_model(name="User Pin", slug="user-pin")

        src_claim = Claim.objects.assert_claim(pm, "year", 1990, source=sources["ipdb"])
        user_claim = Claim.objects.assert_claim(pm, "year", 1991, user=user)
        _set_created_at(src_claim, _T0)
        _set_created_at(user_claim, _T0 + timedelta(days=1))

        # user priority 50 > ipdb priority 10, so the user claim wins.
        self._assert_agree(pm)

    def test_inactive_claim_ignored_by_both(self, sources: dict[str, Source]) -> None:
        pm = make_machine_model(name="Inactive Pin", slug="inactive-pin")
        # assert_claim deactivates the prior claim for the same author+key, so
        # asserting year twice from ipdb leaves one inactive row.
        Claim.objects.assert_claim(pm, "year", 1980, source=sources["ipdb"])
        Claim.objects.assert_claim(pm, "year", 1981, source=sources["ipdb"])
        assert pm.claims.filter(field_name="year", is_active=False).exists()
        self._assert_agree(pm)

    def test_exact_created_at_tie_is_deterministic(
        self, sources: dict[str, Source]
    ) -> None:
        # Two enabled sources of equal priority claim the same cell at an
        # identical created_at — without the "-pk" tiebreak SQL row order is
        # undefined.  Both forms must agree and pick the higher-pk (last) write.
        pm = make_machine_model(name="Tie Pin", slug="tie-pin")
        first = Claim.objects.assert_claim(pm, "year", 1992, source=sources["ipdb"])
        second = Claim.objects.assert_claim(pm, "year", 1993, source=sources["ipdb_b"])
        _set_created_at(first, _T0)
        _set_created_at(second, _T0)  # identical timestamp
        assert second.pk > first.pk
        self._assert_agree(pm)
        assert _sql_winners(pm)["year"].pk == second.pk

    def test_user_versus_user(self, sources: dict[str, Source]) -> None:
        low = get_user_model().objects.create(
            email="low@example.com", username="low", priority=50
        )
        high = get_user_model().objects.create(
            email="high@example.com", username="high", priority=60
        )
        pm = make_machine_model(name="Two User Pin", slug="two-user-pin")
        low_claim = Claim.objects.assert_claim(pm, "year", 1970, user=low)
        high_claim = Claim.objects.assert_claim(pm, "year", 1971, user=high)
        _set_created_at(low_claim, _T0 + timedelta(days=1))  # newer but lower priority
        _set_created_at(high_claim, _T0)
        # Higher user priority wins despite the older created_at.
        self._assert_agree(pm)
        assert _sql_winners(pm)["year"].pk == high_claim.pk

    def test_random_claim_sets_agree(self, db: object) -> None:
        """Property test: the two forms agree across the input space, not just cases.

        The examples above pin known points; the SQL and pure implementations
        are pinned by hand otherwise, so this fuzzes the space — varied priority,
        source vs user, equal priorities, identical ``created_at`` (forcing the
        ``-pk`` tiebreak), inactive claims and disabled sources — so a future
        edge can't slip between them.  Seeded, so a failure reproduces.

        Cheap by construction: ranking never joins to the subject row, so claims
        are fabricated against synthetic ``object_id``s and written in one
        ``bulk_create`` — the whole space is one INSERT plus a few ``created_at``
        updates and two reads.  Committed claims only; pending have no SQL form.
        """
        from django.contrib.contenttypes.models import ContentType

        from apps.accounts.models import User
        from apps.catalog.models import MachineModel

        rng = random.Random(0xC0FFEE)
        sources = [
            Source.objects.create(
                name=f"S{i}", source_type="database", priority=p, is_enabled=en
            )
            for i, (p, en) in enumerate(
                [(0, True), (10, True), (10, True), (20, True), (99, False)]
            )
        ]
        users = [
            User.objects.create(
                email=f"fuzzuser{i}@example.com", username=f"fuzzuser{i}", priority=p
            )
            for i, p in enumerate([10, 60])
        ]
        authors: list[Source | User] = [*sources, *users]
        ct = ContentType.objects.get_for_model(MachineModel)
        field_names = ["name", "year", "manufacturer", "model_number"]
        times = [_T0 + timedelta(days=d) for d in range(3)]  # few buckets → collisions

        claims: list[Claim] = []
        want_time: list[datetime] = []
        for object_id in range(1, 121):
            for field_name in field_names:
                # Distinct authors per (object_id, claim_key): the unique-active
                # constraint allows at most one active claim per (author, key).
                for author in rng.sample(authors, rng.randint(0, len(authors))):
                    source = author if isinstance(author, Source) else None
                    user = None if isinstance(author, Source) else author
                    claims.append(
                        Claim(
                            content_type=ct,
                            object_id=object_id,
                            source=source,
                            user=user,
                            field_name=field_name,
                            claim_key=field_name,
                            value=rng.randint(0, 5),
                            is_active=rng.random() > 0.2,
                        )
                    )
                    want_time.append(rng.choice(times))

        Claim.objects.bulk_create(claims)
        # auto_now_add stamped them all ~now; pin to the chosen buckets.
        by_time: dict[datetime, list[int]] = {}
        for claim, when in zip(claims, want_time, strict=True):
            by_time.setdefault(when, []).append(claim.pk)
        for when, pks in by_time.items():
            Claim.objects.filter(pk__in=pks).update(created_at=when)

        # SQL winners for every subject in one ordered query.
        sql_winners: dict[tuple[int, str], int] = {}
        for claim in ranked_claims(
            Claim.objects.filter(content_type=ct), "object_id", "claim_key"
        ):
            sql_winners.setdefault((claim.object_id, claim.claim_key), claim.pk)

        # Pure winners: pick_winners per subject over the same claims; also count
        # eligible claims per group to prove the fuzz genuinely contested picks.
        by_object: dict[int, list[Claim]] = {}
        eligible_per_group: Counter[tuple[int, str]] = Counter()
        for claim in Claim.objects.filter(content_type=ct).select_related(
            "source", "user"
        ):
            by_object.setdefault(claim.object_id, []).append(claim)
            if is_eligible(claim):
                eligible_per_group[claim.object_id, claim.claim_key] += 1
        pure_winners = {
            (object_id, key): winner.pk
            for object_id, group in by_object.items()
            for key, winner in pick_winners(group).items()
        }

        # Guard against a vacuous pass: at least one key must have >=2 *eligible*
        # claims, so the tiebreak was genuinely exercised — not just singletons
        # or dropped inactive/disabled losers.
        assert max(eligible_per_group.values(), default=0) >= 2, (
            "fuzz produced no contested group (no key had >=2 eligible claims)"
        )

        disagreements = {
            key
            for key in sql_winners.keys() | pure_winners.keys()
            if sql_winners.get(key) != pure_winners.get(key)
        }
        assert not disagreements, (
            f"SQL and pure winner-pick disagree on "
            f"{sorted(disagreements)[:10]} (random seed 0xC0FFEE)"
        )


# --------------------------------------------------------------------------
# Real-consumer tests — run the actual resolvers, not a hand-written mirror.
# --------------------------------------------------------------------------


class TestRealResolverConsumers:
    """Exact ties must resolve to the last write through the *real* resolvers.

    ``_sql_winners`` replicates the order; these run the production paths
    (generic entity + MachineModel) so a consumer that bypassed the shared
    ``ranked_claims`` — the original drift — would fail here even though the
    local mirror still agreed with ``pick_winners``.
    """

    @staticmethod
    def _tie_sources() -> tuple[Source, Source]:
        """Two enabled sources of equal priority — the exact-tie precondition."""
        a = Source.objects.create(name="Src A", source_type="database", priority=10)
        b = Source.objects.create(name="Src B", source_type="database", priority=10)
        return a, b

    def test_generic_entity_resolver_breaks_tie_by_last_write(self, db: object) -> None:
        from apps.catalog.models import Title

        src_a, src_b = self._tie_sources()
        title = Title.objects.create(name="Placeholder", slug="tie-title")
        first = Claim.objects.assert_claim(title, "name", "Alpha", source=src_a)
        second = Claim.objects.assert_claim(title, "name", "Beta", source=src_b)
        _set_created_at(first, _T0)
        _set_created_at(second, _T0)  # exact tie: equal priority + created_at
        assert second.pk > first.pk

        resolve_all_entities(Title)
        title.refresh_from_db()
        # _entities.py now goes through ranked_claims, so it picks the last write
        # — matching pick_winners, not undefined DB row order.
        assert title.name == "Beta"
        winners = pick_winners(list(title.claims.select_related("source", "user")))
        assert winners["name"].value == "Beta"

    def test_machine_model_resolver_breaks_tie_by_last_write(self, db: object) -> None:
        src_a, src_b = self._tie_sources()
        pm = make_machine_model(name="Placeholder", slug="tie-mm")
        first = Claim.objects.assert_claim(pm, "name", "Alpha", source=src_a)
        second = Claim.objects.assert_claim(pm, "name", "Beta", source=src_b)
        _set_created_at(first, _T0)
        _set_created_at(second, _T0)
        assert second.pk > first.pk

        resolve_model(pm)
        pm.refresh_from_db()
        assert pm.name == "Beta"
