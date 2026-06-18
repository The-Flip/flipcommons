"""Relationship-member presence — does a member claim assert the member exists?

A member claim carries an ``exists`` flag; ``exists=false`` is a tombstone (a
recorded removal).  This answers presence for a *single, already-selected*
claim — it does not rank or select.  The caller chooses the selection, and that
choice is what distinguishes two reads that must never be conflated:

* a *source-scoped* read (the ``remove:`` no-op check) feeds it one source's own
  current claim — "does this source still assert the member?";
* a *resolved* read feeds it the cross-source winning claim — "does the member
  survive resolution across all sources?".

Never pass a raw, unranked multi-source claim list: source-filter or rank first,
then ask this.  And never pass a *scalar/FK* claim — a scalar value cannot be
distinguished from a member tombstone by shape (``Location.divisions`` and
``extra_data`` are claim-controlled JSON scalar fields, so a scalar value can
itself be a dict carrying an ``exists`` key).  Scalar presence is plain
existence of the claim; the member dimension is carried by the caller (a
relationship namespace), never inferred from the value.
"""

from __future__ import annotations

from typing import Protocol


class PresenceClaim(Protocol):
    """A claim projected onto just its asserted ``value`` — what presence reads.

    Satisfied structurally by the ORM :class:`apps.provenance.models.Claim` and
    by any unsaved object exposing the asserted ``value``.
    """

    @property
    def value(self) -> object: ...


def member_is_present(claim: PresenceClaim | None) -> bool:
    """Whether a relationship-member *claim* asserts the member is present.

    ``None`` (the selection found no member claim) reads as absent.  A member
    claim with ``exists=false`` is a tombstone and reads as absent.  A claim
    whose value is not a JSON object reads as absent rather than raising.

    Pass only *member* claims — see the module docstring on why scalar/FK claims
    must not route through here.
    """
    if claim is None:
        return False
    value = claim.value
    # A member payload is a JSON object whose ``exists`` flag (default true)
    # marks presence; a tombstone sets it false.  A non-object value is malformed
    # for a member claim and reads absent.
    return isinstance(value, dict) and bool(value.get("exists", True))
