"""Unit tests for the catalog-free resolution primitives in ``_engine``."""

from __future__ import annotations

from apps.catalog.resolve._engine import pick_member_winners, pick_winners
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
