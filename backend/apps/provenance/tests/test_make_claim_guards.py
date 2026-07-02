"""Guards on the ``make_claim`` test factory's attribution invariants.

The factory exists to make attribution mistakes fail at call time. These lock
that: exactly one attribution target, and an explicit changeset must agree with
any target passed alongside it.
"""

from __future__ import annotations

import pytest

from apps.catalog.models import Manufacturer
from apps.provenance.test_factories import (
    make_claim,
    make_ingest_source,
    user_changeset,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def subject():
    return Manufacturer.objects.create(name="Williams", slug="williams")


class TestMakeClaimAttributionGuards:
    def test_rejects_user_and_source_together(self, subject, user):
        with pytest.raises(ValueError, match="at most one"):
            make_claim(
                subject,
                "name",
                "Williams",
                user=user,
                ingest_source=make_ingest_source(),
            )

    def test_rejects_user_and_source_even_with_changeset(self, subject, user):
        # The regression: with an explicit changeset the old code checked only
        # user= and silently ignored a mismatched source=. Now rejected up front.
        cs = user_changeset(user)
        with pytest.raises(ValueError, match="at most one"):
            make_claim(
                subject,
                "name",
                "Williams",
                user=user,
                ingest_source=make_ingest_source(),
                changeset=cs,
            )

    def test_requires_some_attribution(self, subject):
        with pytest.raises(
            ValueError, match="Provide a source, a user, or a changeset"
        ):
            make_claim(subject, "name", "Williams")

    def test_changeset_actor_must_match_supplied_target(self, subject, user):
        # source= disagrees with the changeset's (user) actor — must fail loudly
        # rather than silently attribute to the changeset.
        cs = user_changeset(user)
        with pytest.raises(ValueError, match="does not match"):
            make_claim(
                subject,
                "name",
                "Williams",
                ingest_source=make_ingest_source(),
                changeset=cs,
            )
