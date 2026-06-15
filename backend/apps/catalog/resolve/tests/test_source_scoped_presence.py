"""Source-scoped presence is a *source-scoped* read, not a resolved one.

The ``retract:`` / ``remove:`` no-op check asks "does *this source's* own current
claim assert presence?" — not "what wins resolution across all sources?".  These
tests pin that distinction so the two are never conflated: reading the no-op off
the cross-source winner would give the wrong verdict when another source owns a
member, or wins a tombstone.

The two no-op dimensions stay separate, because they genuinely are:

* **scalar/FK** (``retract:``) — presence is plain existence ("does the source
  hold a current claim?").  It must *not* inspect the claim value: a
  claim-controlled JSON scalar (``Location.divisions``, ``extra_data``) can be a
  dict carrying an ``exists`` key, which a value-predicate would misread as a
  tombstone.
* **member** (``remove:``) — presence is the ``exists`` filter
  (:func:`member_is_present`).

``_source_claims_member_present`` is built on :func:`member_is_present` (one
definition for the member exists-filter), so the tests below pin its *behavior*
end-to-end rather than re-comparing two copies.

Layers: pure-unit edges of :func:`member_is_present` (no database); the
production no-op checks read correctly on committed claims (``_source_claims_field``
for scalar existence, ``_source_claims_member_present`` for member
presence/tombstone); and the divergence guard — the source-scoped no-op vs the
cross-source ``pick_winners`` winner give opposite verdicts when another source
owns a member, or wins a tombstone.  Pending same-patch claims are out of scope
here — these read committed state.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from django.contrib.contenttypes.models import ContentType

from apps.catalog.claims import build_relationship_claim
from apps.catalog.ingestion.patches.emit import (
    _source_claims_field,
    _source_claims_member_present,
)
from apps.catalog.models import CatalogModel, Location, Manufacturer
from apps.catalog.resolve.claim_presence import member_is_present
from apps.catalog.resolve.claim_ranking_in_memory import pick_winners
from apps.provenance.models import Claim, Source

_ALIAS_NS = "manufacturer_alias"


# ---------------------------------------------------------------------------
# Pure-unit edges of the member exists-filter (no database).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FakeClaim:
    """A claim projected onto just its ``value`` — all the filter reads."""

    value: object


class TestMemberIsPresent:
    def test_none_is_absent(self) -> None:
        # The selection found no member claim from this author → absent.
        assert member_is_present(None) is False

    def test_exists_true_is_present(self) -> None:
        assert member_is_present(_FakeClaim({"alias_value": "x", "exists": True}))

    def test_tombstone_is_absent(self) -> None:
        assert not member_is_present(_FakeClaim({"alias_value": "x", "exists": False}))

    def test_missing_exists_defaults_present(self) -> None:
        # Mirrors production's ``value.get("exists", True)`` — an absent flag is
        # presence, matching a relationship payload without an explicit
        # tombstone.
        assert member_is_present(_FakeClaim({"alias_value": "x"})) is True

    def test_non_dict_value_is_absent(self) -> None:
        # Mirrors production's ``isinstance(value, dict) and ...`` — a malformed
        # member claim reads absent rather than raising.
        assert member_is_present(_FakeClaim("not-a-dict")) is False


# ---------------------------------------------------------------------------
# The production no-op checks, on committed claims.
# ---------------------------------------------------------------------------


@pytest.fixture
def source(db: object) -> Source:
    return Source.objects.create(name="Patch", source_type="editorial", priority=100)


def _source_current_claim(
    source: Source, entity: CatalogModel, claim_key: str
) -> Claim | None:
    """The source's single committed active claim for a cell, or ``None``.

    Committed state holds at most one active claim per (source, claim_key) by the
    ``assert_claim`` invariant, so ``.first()`` *is* the source's current claim.
    Same-patch pending claims are out of scope here — this reads committed state.
    """
    ct_id = ContentType.objects.get_for_model(entity).pk
    return Claim.objects.filter(
        source=source,
        is_active=True,
        content_type_id=ct_id,
        object_id=entity.pk,
        claim_key=claim_key,
    ).first()


def _assert_scalar_agrees(source: Source, entity: CatalogModel, field: str) -> None:
    # The scalar source-scoped read is plain existence — never the exists-filter.
    ct_id = ContentType.objects.get_for_model(entity).pk
    production = _source_claims_field(source, ct_id, entity.pk, field)
    in_memory = _source_current_claim(source, entity, field) is not None
    assert production == in_memory


def test_scalar_present_and_absent_agree(source: Source) -> None:
    mfr = Manufacturer.objects.create(name="Gottlieb", slug="gottlieb")

    # No claim from this source → both read absent (a no-op retract).
    _assert_scalar_agrees(source, mfr, "name")

    # Source holds an active scalar claim → both read present.
    Claim.objects.assert_claim(mfr, "name", "Gottlieb Inc", source=source)
    _assert_scalar_agrees(source, mfr, "name")


def test_scalar_dict_value_reads_present_not_as_a_tombstone(source: Source) -> None:
    """The scalar/member split, proven on a real claim-controlled JSON scalar.

    ``Location.divisions`` is a scalar (DIRECT) claim whose value is free-form
    JSON — here a dict that happens to carry ``exists: false``.  The source holds
    the claim, so the scalar no-op reads it *present* (``_source_claims_field``);
    routing the same claim through the member exists-filter would misread the
    dict as a tombstone and call it absent.  That divergence is exactly why the
    scalar read is plain existence and must never go through member_is_present.
    """
    loc = Location.objects.create(
        location_path="usa", slug="usa", name="USA", location_type="country"
    )
    Claim.objects.assert_claim(
        loc,
        "divisions",
        {"exists": False, "note": "free-form scalar JSON"},
        source=source,
    )
    ct_id = ContentType.objects.get_for_model(loc).pk
    current = _source_current_claim(source, loc, "divisions")

    # Scalar = existence (present); member exists-filter on the same claim = absent.
    assert _source_claims_field(source, ct_id, loc.pk, "divisions") is True
    assert member_is_present(current) is False


def test_member_no_op_check_reads_present_tombstone_and_absent(source: Source) -> None:
    mfr = Manufacturer.objects.create(name="Bally", slug="bally")
    ct_id = ContentType.objects.get_for_model(mfr).pk
    claim_key, present = build_relationship_claim(
        _ALIAS_NS, {"alias_value": "bally corp", "alias_display": "Bally Corp"}
    )

    # Never claimed → absent (removing it is a no-op).
    assert _source_claims_member_present(source, ct_id, mfr.pk, claim_key) is False

    # exists=true membership → present.
    Claim.objects.assert_claim(
        mfr, _ALIAS_NS, present, source=source, claim_key=claim_key
    )
    assert _source_claims_member_present(source, ct_id, mfr.pk, claim_key) is True

    # Tombstone (exists=false) supersedes it → absent again.
    _, tombstone = build_relationship_claim(
        _ALIAS_NS, {"alias_value": "bally corp"}, exists=False
    )
    Claim.objects.assert_claim(
        mfr, _ALIAS_NS, tombstone, source=source, claim_key=claim_key
    )
    assert _source_claims_member_present(source, ct_id, mfr.pk, claim_key) is False


def test_member_owned_by_another_source_is_a_no_op_for_ours(source: Source) -> None:
    """A member only *another* source claims is a no-op for ours to remove."""
    other = Source.objects.create(name="Other", source_type="database", priority=200)
    mfr = Manufacturer.objects.create(name="Williams", slug="williams")
    ct_id = ContentType.objects.get_for_model(mfr).pk
    claim_key, present = build_relationship_claim(
        _ALIAS_NS, {"alias_value": "wms", "alias_display": "WMS"}
    )
    Claim.objects.assert_claim(
        mfr, _ALIAS_NS, present, source=other, claim_key=claim_key
    )
    # Our source holds nothing here → no-op (source-scoped, not resolved).
    assert _source_claims_member_present(source, ct_id, mfr.pk, claim_key) is False


# ---------------------------------------------------------------------------
# The divergence guard — source-scoped selection vs the resolved winner.
# ---------------------------------------------------------------------------


def _resolved_member_presence(entity: CatalogModel, claim_key: str) -> bool:
    """Presence of the *cross-source* winner — the resolved read, for contrast.

    Runs the same :func:`member_is_present` filter over what ``pick_winners``
    selects, so the only difference from the source-scoped no-op is the
    **selection**.  This is what the no-op check must *not* use.

    TODO: the patch front end will own a shared ``resolve_present_members``
    (``pick_winners`` + :func:`member_is_present` over committed + pending
    claims); switch this preview to call it rather than keep a second copy of
    the composition.
    """
    claims = list(entity.claims.select_related("source", "user").all())
    return member_is_present(pick_winners(claims).get(claim_key))


def test_source_scoped_diverges_when_other_source_owns_member(source: Source) -> None:
    """Another source owns a member: resolved=present, source-scoped=absent.

    Removing a member you do not own is a no-op even though it resolves present
    — so the no-op check must read source-scoped, not resolved.
    """
    other = Source.objects.create(name="Other", source_type="database", priority=200)
    mfr = Manufacturer.objects.create(name="Stern", slug="stern")
    ct_id = ContentType.objects.get_for_model(mfr).pk
    claim_key, present = build_relationship_claim(
        _ALIAS_NS, {"alias_value": "stern pinball", "alias_display": "Stern Pinball"}
    )
    Claim.objects.assert_claim(
        mfr, _ALIAS_NS, present, source=other, claim_key=claim_key
    )

    resolved = _resolved_member_presence(mfr, claim_key)
    source_scoped = _source_claims_member_present(source, ct_id, mfr.pk, claim_key)
    assert resolved is True
    assert source_scoped is False


def test_source_scoped_diverges_when_other_source_wins_tombstone(
    source: Source,
) -> None:
    """A higher-priority tombstone wins: resolved=absent, source-scoped=present.

    Our source still owns its ``exists=true`` claim, so *our* remove is a real
    change, not a no-op — even though the member resolves absent under the
    winning tombstone.  Source-scoped again diverges from resolved.
    """
    winner = Source.objects.create(name="Winner", source_type="editorial", priority=300)
    mfr = Manufacturer.objects.create(name="Data East", slug="data-east")
    ct_id = ContentType.objects.get_for_model(mfr).pk
    claim_key, present = build_relationship_claim(
        _ALIAS_NS, {"alias_value": "de", "alias_display": "DE"}
    )
    _, tombstone = build_relationship_claim(
        _ALIAS_NS, {"alias_value": "de"}, exists=False
    )
    # Our (lower-priority) source asserts presence; the winner tombstones it.
    Claim.objects.assert_claim(
        mfr, _ALIAS_NS, present, source=source, claim_key=claim_key
    )
    Claim.objects.assert_claim(
        mfr, _ALIAS_NS, tombstone, source=winner, claim_key=claim_key
    )

    resolved = _resolved_member_presence(mfr, claim_key)
    source_scoped = _source_claims_member_present(source, ct_id, mfr.pk, claim_key)
    assert resolved is False
    assert source_scoped is True
