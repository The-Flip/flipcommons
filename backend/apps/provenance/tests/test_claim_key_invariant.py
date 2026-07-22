"""``claim_key`` must stay derivable from ``field_name``.

``claim_key`` is not independent data — ``make_claim_key`` computes it *from*
``field_name``, returning either ``field_name`` verbatim (scalar claims) or
``field_name`` joined to sorted identity parts by ``|`` (relationship claims).
It is materialized into a column so the partial-unique index and the grouping
index can exist, which makes it a denormalized cache carrying the usual
obligation: change the input, recompute the output.

Catalog migration ``0026`` changed ``field_name`` on 2322 rows and did not
recompute ``claim_key``, leaving rows that advertise a slot no longer derivable
from anything they contain. Nothing rejected it — the canonicality check
(``validation`` rule 8) runs only for relationship claims, and a migration's
raw ``.update()`` skips model validation entirely. The database is the only
layer that sees a migration coming, so the backstop lives there; the second
half of this file covers the validation-boundary check in front of it.

The constraint is deliberately weaker than the full rule: it cannot know which
claims are relationship claims (that needs ``_meta`` introspection), so it
asserts the structural property that holds for *both* shapes — ``claim_key`` is
``field_name``, or ``field_name`` followed by the ``|`` separator. That is
enough to catch an input changed without its output.
"""

from __future__ import annotations

import logging

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError

from apps.catalog.models import Manufacturer, Theme
from apps.catalog.tests.conftest import make_machine_model
from apps.provenance.models import Claim, make_claim_key
from apps.provenance.test_factories import user_changeset
from apps.provenance.validation import validate_claims_batch

pytestmark = pytest.mark.django_db

_CONSTRAINT = "provenance_claim_key_derived_from_field_name"


@pytest.fixture
def mfr():
    return Manufacturer.objects.create(name="Williams", slug="williams")


def _write(mfr: Manufacturer, user, *, field_name: str, claim_key: str) -> Claim:
    """Insert a Claim row directly, bypassing the write primitive.

    ``claim_writer`` defaults ``claim_key`` to ``field_name``, so the drifted
    shape can only be built by going around it — which is exactly what the
    migration did.

    These rows never pass through ``classify_claim``, and the constraint is
    purely structural, so the field names below need not be real fields on the
    subject. Only the shape of the two strings matters.
    """
    return Claim.objects.create(
        content_type=ContentType.objects.get_for_model(Manufacturer),
        object_id=mfr.pk,
        actor=user.actor,
        changeset=user_changeset(user),
        field_name=field_name,
        claim_key=claim_key,
        value="Williams Electronics",
    )


def test_drifted_claim_key_is_rejected(mfr, user):
    """The 0026 shape: field_name renamed, claim_key left on the old name."""
    with pytest.raises(IntegrityError, match=_CONSTRAINT):
        _write(
            mfr,
            user,
            field_name="manufacturer_model_identifier",
            claim_key="ipdb.model_number",
        )


def test_scalar_claim_key_equal_to_field_name_is_accepted(mfr, user):
    """The canonical scalar shape — ``make_claim_key`` with no identity parts."""
    claim = _write(mfr, user, field_name="name", claim_key=make_claim_key("name"))

    assert claim.claim_key == "name"


def test_relationship_claim_key_is_accepted(mfr, user):
    """The canonical relationship shape — field_name plus sorted identity parts."""
    claim_key = make_claim_key("theme", theme=153)
    claim = _write(mfr, user, field_name="theme", claim_key=claim_key)

    assert claim.claim_key == "theme|theme:153"


def test_shared_prefix_without_separator_is_rejected(mfr, user):
    """``name`` → ``names`` is drift, not a namespace.

    Pins the separator half of the rule: a claim_key that merely *starts with*
    the field name is not derivable from it. Also the case a ``LIKE``-based
    spelling would wave through, since ``_`` and ``%`` are wildcards there and
    field names are full of underscores.
    """
    with pytest.raises(IntegrityError, match=_CONSTRAINT):
        _write(mfr, user, field_name="name", claim_key="names")


def test_wildcard_lookalike_field_name_is_rejected(mfr, user):
    """``_`` in a field name is a literal, not a single-character wildcard."""
    with pytest.raises(IntegrityError, match=_CONSTRAINT):
        _write(mfr, user, field_name="short_name", claim_key="shortXname")


# ---------------------------------------------------------------------------
# The same rule at the validation boundary
#
# The constraint is the backstop, because it is the only layer a migration
# cannot walk past. But claims arriving through ``claim_ingest`` carry whatever
# claim_key the patch supplied (``pca.claim_key or pca.field_name``), so a patch
# can hand a direct field a foreign key. Catching it here turns an
# IntegrityError that aborts the whole ingest into one logged, dropped claim.
# ---------------------------------------------------------------------------


def test_direct_claim_with_foreign_claim_key_is_rejected(mfr):
    """A scalar field may not carry someone else's slot."""
    claim = Claim.for_object(
        mfr, field_name="name", value="Williams", claim_key="ipdb.model_number"
    )

    valid, rejected = validate_claims_batch([claim])

    assert rejected == 1
    assert valid == []


def test_direct_claim_with_blank_claim_key_is_accepted(mfr):
    """Blank is the normal pre-write state — ``claim_writer`` derives it."""
    claim = Claim.for_object(mfr, field_name="name", value="Williams")

    valid, rejected = validate_claims_batch([claim])

    assert rejected == 0
    assert len(valid) == 1


def test_extra_data_claim_with_foreign_claim_key_is_rejected():
    """Parked extra_data claims are scalar too, so the same rule binds them.

    Worth pinning because extra_data is the loosest branch — it accepts any
    field name at all, and before this check it looked at nothing else. The
    healthy rows catalog 0026 inherited had ``ipdb.model_number`` in *both*
    columns; it was the promotion that split them.
    """
    model = make_machine_model(name="Eight Ball", slug="eight-ball")
    claim = Claim.for_object(
        model,
        field_name="ipdb.model_number",
        value="11000-LE",
        claim_key="manufacturer_model_identifier",
    )

    valid, rejected = validate_claims_batch([claim])

    assert rejected == 1
    assert valid == []


def test_relationship_claim_with_compound_key_still_passes(credit_targets):
    """The one shape that legitimately diverges must survive the check.

    Guards against the guard: the equality rule sits in the same dispatch as
    the RELATIONSHIP branch, so getting its condition wrong would reject every
    relationship claim in the system rather than none.
    """
    model = make_machine_model(name="Test", slug="test")
    person_pk = credit_targets["persons"]["pat-lawlor"].pk
    role_pk = credit_targets["roles"]["design"].pk
    claim = Claim.for_object(
        model,
        field_name="credit",
        value={"person": person_pk, "role": role_pk, "exists": True},
        claim_key=make_claim_key("credit", person=person_pk, role=role_pk),
    )

    valid, rejected = validate_claims_batch([claim])

    assert rejected == 0
    assert len(valid) == 1


def test_unrecognized_field_reports_the_field_not_the_claim_key(caplog):
    """A bad field name is the root cause; the claim_key is downstream noise.

    Both faults are present here. The check deliberately skips UNRECOGNIZED so
    the warning names the thing worth fixing — otherwise a patch with a typo'd
    field name gets a rejection message pointing at the wrong column.

    Uses ``Theme`` rather than ``Manufacturer`` because 18 of the 21
    claim-controlled models have no ``extra_data`` column, and only those can
    reach UNRECOGNIZED at all — on the other three an unknown field name is
    simply parked as EXTRA.
    """
    theme = Theme.objects.create(name="Medieval", slug="medieval")
    claim = Claim.for_object(
        theme, field_name="nmae", value="Medieval", claim_key="something.else"
    )

    with caplog.at_level(logging.WARNING):
        valid, rejected = validate_claims_batch([claim])

    assert rejected == 1
    assert valid == []
    assert "unrecognized field_name" in caplog.text
    assert "claim_key" not in caplog.text
