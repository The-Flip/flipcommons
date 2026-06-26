"""Unit tests for the catalog-free resolution primitives in ``_engine``."""

from __future__ import annotations

from collections.abc import Iterable

from apps.catalog.resolve._engine import (
    Delta,
    ExtractedMember,
    MemberMap,
    RowState,
    _build_desired,
    diff,
    pick_member_winners,
    pick_winners,
)
from apps.provenance.models import Claim


def test_pick_winners_keeps_first_per_group() -> None:
    """The first claim seen per (subject, group) wins; later ones are dropped."""
    # Unsaved instances — pick_winners only reads attributes and never hits the
    # DB.  Use identity checks (`is`): unsaved Claims share pk=None, so `==`
    # would treat them all as equal.
    winner = Claim(object_id=1, claim_key="k", field_name="name")
    loser = Claim(object_id=1, claim_key="k", field_name="name")  # same group, later

    winners = pick_winners(
        [winner, loser], lambda c: c.object_id, lambda c: c.claim_key
    )

    assert winners[1]["k"] is winner


def test_pick_winners_partitions_by_subject_and_group() -> None:
    """Distinct subjects and group keys land in their own slots."""
    s1k1 = Claim(object_id=1, claim_key="a", field_name="x")
    s1k2 = Claim(object_id=1, claim_key="b", field_name="x")
    s2k1 = Claim(object_id=2, claim_key="a", field_name="x")

    winners = pick_winners(
        [s1k1, s1k2, s2k1], lambda c: c.object_id, lambda c: c.claim_key
    )

    assert set(winners) == {1, 2}
    assert winners[1]["a"] is s1k1
    assert winners[1]["b"] is s1k2
    assert winners[2]["a"] is s2k1


def test_pick_winners_empty() -> None:
    """No claims yields an empty map, not an error."""
    assert pick_winners([], lambda c: c.object_id, lambda c: c.claim_key) == {}


def test_pick_winners_accepts_a_composite_subject() -> None:
    """The subject extractor may return a composite (hashable) key — the media
    ``(content_type_id, object_id)`` shape."""
    a = Claim(content_type_id=3, object_id=1, claim_key="k", field_name="media")
    b = Claim(content_type_id=4, object_id=1, claim_key="k", field_name="media")

    winners = pick_winners(
        [a, b],
        lambda c: (c.content_type_id, c.object_id),
        lambda c: c.claim_key,
    )

    assert winners[(3, 1)]["k"] is a
    assert winners[(4, 1)]["k"] is b


def test_pick_member_winners_groups_by_object_id_and_claim_key() -> None:
    """The membership wrapper keys subjects on object_id, members on claim_key."""
    winner = Claim(object_id=7, claim_key="theme:1", field_name="theme")
    loser = Claim(object_id=7, claim_key="theme:1", field_name="theme")  # later
    other = Claim(object_id=7, claim_key="theme:2", field_name="theme")

    winners = pick_member_winners([winner, other, loser])

    assert winners[7]["theme:1"] is winner
    assert winners[7]["theme:2"] is other


# ---------------------------------------------------------------------------
# diff — the three-way set/map difference
# ---------------------------------------------------------------------------


def test_diff_partitions_create_delete_and_keeps_unchanged() -> None:
    """A member only desired → create; only existing → delete; both → no-op."""
    desired = {1: {"keep": None, "add": None}}
    existing = {1: {"keep": RowState(10, None), "drop": RowState(11, None)}}

    delta = diff(desired, existing)

    assert [(c.subject, c.key) for c in delta.create] == [(1, "add")]
    assert delta.delete == [11]
    assert delta.update == []


def test_diff_update_branch_fires_only_on_payload_change() -> None:
    """For a map membership, a member present in both diffs by payload value."""
    desired = {1: {"a": 5, "b": 9}}
    existing = {1: {"a": RowState(10, 5), "b": RowState(11, 3)}}  # a same, b changed

    delta = diff(desired, existing)

    assert delta.create == []
    assert delta.delete == []
    assert delta.update == [(11, 9)]


def test_diff_update_branch_is_vacuous_for_a_set() -> None:
    """With ``Payload=None`` there is no value to differ on, so update stays empty."""
    desired = {1: {"x": None}}
    existing = {1: {"x": RowState(10, None)}}

    assert diff(desired, existing).update == []


def test_diff_visits_subjects_present_only_in_existing() -> None:
    """A subject whose claims all went away still has its stale rows deleted."""
    desired: dict[int, dict[str, None]] = {}
    existing = {2: {"gone": RowState(20, None)}}

    delta = diff(desired, existing)

    assert delta.create == []
    assert delta.delete == [20]


def test_diff_is_idempotent_once_converged() -> None:
    """Re-diffing desired against a matching existing writes nothing."""
    desired = {1: {"a": 5}}
    converged = {1: {"a": RowState(10, 5)}}

    delta = diff(desired, converged)

    assert delta == ([], [], [])


# ---------------------------------------------------------------------------
# _build_desired — member_is_present is the one engine-side built-in filter
# ---------------------------------------------------------------------------


class _KeyProjection:
    """Projection stub for testing the engine loop: ``extract`` echoes the
    claim_key as the member; the other methods are unused by ``_build_desired``."""

    def claims(self, subjects: set[int] | None) -> Iterable[Claim]:
        return []

    def subject(self, claim: Claim) -> int:
        return claim.object_id

    def extract(self, claim: Claim) -> ExtractedMember[str, None]:
        return ExtractedMember(claim.claim_key, None)

    def read(self, subjects: set[int] | None) -> MemberMap[int, str, RowState[None]]:
        return {}

    def write(self, delta: Delta[int, str, None]) -> None:
        pass


def test_build_desired_drops_exists_false_tombstones() -> None:
    """A winning claim whose value is an ``exists=false`` tombstone is dropped;
    a present member survives — the filter the engine runs for every projection."""
    present = Claim(object_id=1, claim_key="a", field_name="x", value={"exists": True})
    tombstone = Claim(
        object_id=1, claim_key="b", field_name="x", value={"exists": False}
    )
    winners: MemberMap[int, str, Claim] = {1: {"a": present, "b": tombstone}}

    desired = _build_desired(_KeyProjection(), winners)

    assert desired == {1: {"a": None}}
