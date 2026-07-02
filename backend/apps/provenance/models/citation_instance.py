"""CitationInstance: a specific use of a CitationSource with a locator."""

from __future__ import annotations

import re
from typing import Any

from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.db.models.functions import Length, Now
from django.utils.crypto import get_random_string

from apps.core.types import CitationSourceId
from apps.core.validators import validate_no_mojibake

CITATION_INSTANCE_LOCATOR_MAX_LENGTH = 200

# Slug alphabet: lowercase consonants only (vowels dropped). Digit-free so a
# slug can never collide with a numeric same-patch cite handle, and vowel-free
# so a slug can't accidentally spell a real word. 21 chars ^ 8 ≈ 3.8e10 space.
CITATION_SLUG_ALPHABET = "bcdfghjklmnpqrstvwxyz"
CITATION_SLUG_LENGTH = 8
# Retries on the (vanishingly rare) unique-slug collision before giving up.
_MINT_MAX_ATTEMPTS = 5

_SLUG_RE = re.compile(rf"\A[{CITATION_SLUG_ALPHABET}]{{{CITATION_SLUG_LENGTH}}}\Z")

# Register so the slug-length CHECK constraint below can use ``slug__length``.
# Django ships Length but doesn't auto-register it (it adds a query-time call by
# default); register_lookup is idempotent, so doing it here is safe even though
# apps.accounts also registers it.
models.CharField.register_lookup(Length)


def generate_citation_slug() -> str:
    """Generate a random, digit-free, author-stable citation slug.

    Not collision-checked here — uniqueness is enforced by the DB constraint
    and the mint helper's savepoint-wrapped retry.
    """
    return get_random_string(CITATION_SLUG_LENGTH, CITATION_SLUG_ALPHABET)


def validate_citation_slug(value: str) -> None:
    """Enforce the slug grammar: exactly ``CITATION_SLUG_LENGTH`` lowercase
    consonants (digit-free, vowel-free).

    Load-bearing: Step 2 classifies a cite marker handle lexically (all-digits =
    a new citation, all-lowercase-letters = an existing slug), so a digit or
    wrong-length slug would later be emitted by ``convert_storage_to_authoring``
    and rejected by the patch grammar. The charset half can't be a portable DB
    CHECK (``__regex`` isn't enforceable in SQLite CHECK DDL), so it lives here;
    the DB carries only the cross-backend length CHECK.
    """
    if not _SLUG_RE.match(value):
        raise ValidationError(
            f"Invalid citation slug {value!r}: expected {CITATION_SLUG_LENGTH} "
            "lowercase consonants (digit-free, vowel-free)."
        )


class CitationInstanceManager(models.Manager["CitationInstance"]):
    """Manager whose ``mint_many`` assigns unique slugs before ``bulk_create``.

    Single-row creates (``save()``/``objects.create()``) get their slug from
    ``CitationInstance.save()``. ``bulk_create`` skips ``save()``, so the bulk
    paths (ingest's scalar attach, and step 2's inline materialize) must go
    through here to populate the NOT NULL/unique ``slug`` column.
    """

    def mint_many(self, instances: list[CitationInstance]) -> list[CitationInstance]:
        """Assign unique slugs to every instance and ``bulk_create`` them.

        On a unique-slug collision we can't tell which row clashed (a partial
        ``bulk_create`` reports nothing), so regenerate ALL slugs and retry the
        whole batch. Each attempt runs in its own ``atomic()`` savepoint: a
        caller may already be inside ``transaction.atomic()`` (the ingest apply
        path is), where an ``IntegrityError`` poisons the outer transaction —
        the savepoint lets the failed insert roll back and the retry run clean.
        """
        if not instances:
            return []
        for attempt in range(_MINT_MAX_ATTEMPTS):
            for inst in instances:
                inst.slug = generate_citation_slug()
            try:
                with transaction.atomic():
                    self.bulk_create(instances)
                return instances
            except IntegrityError:
                if attempt == _MINT_MAX_ATTEMPTS - 1:
                    raise
        # Unreachable: the final attempt either returns or re-raises.
        raise AssertionError("mint retry loop exited without result")


class CitationInstance(models.Model):
    """A specific use of a CitationSource at a point in text, with a locator.

    Immutable: corrections create a new instance (old one becomes orphaned).
    Only has created_at, no updated_at — matching the Claim immutability pattern.

    An instance is shared evidence: scalar/edit claims reach it through the
    ``ClaimCitationInstance`` join, and inline markdown citations
    (``[[cite:id:...]]``) reach it through their marker alone.

    ``slug`` is a globally-unique, digit-free, author-stable handle. It is the
    authoring key for the ``cite`` wikilink type (``[[cite:<slug>]]`` authoring
    ↔ ``[[cite:id:<pk>]]`` storage). Every instance carries one, including
    scalar/edit cites whose slug simply goes unused — a uniform column beats a
    conditional constraint. Assigned at mint, immutable.
    """

    citation_source_id: CitationSourceId

    slug = models.CharField(max_length=CITATION_SLUG_LENGTH, unique=True)
    citation_source = models.ForeignKey(
        "citation.CitationSource",
        on_delete=models.PROTECT,
        related_name="instances",
    )
    locator = models.CharField(
        max_length=CITATION_INSTANCE_LOCATOR_MAX_LENGTH,
        blank=True,
        default="",
        db_default="",
        validators=[validate_no_mojibake],
    )
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    objects = CitationInstanceManager()

    class Meta:
        constraints = [
            # Cross-backend belt for the slug length. The charset half is
            # app-layer (validate_citation_slug) since __regex isn't enforceable
            # in SQLite CHECK DDL; this catches a wrong-length slug even on the
            # bulk_create path that skips save().
            models.CheckConstraint(
                condition=models.Q(slug__length=CITATION_SLUG_LENGTH),
                name="prov_citinst_slug_length",
            ),
        ]
        indexes = [
            models.Index(
                fields=["citation_source"],
                name="prov_citinst_source_idx",
            ),
        ]

    def __str__(self) -> str:
        loc = f" @ {self.locator}" if self.locator else ""
        return f"Citation: {self.citation_source_id}{loc}"

    # Django's Model.save signature is owned by the framework; the override
    # only enforces immutability before delegating upstream.
    def save(
        self,
        *args: Any,  # noqa: ANN401
        **kwargs: Any,  # noqa: ANN401
    ) -> None:
        if self.pk is not None:
            raise ValueError(
                "CitationInstance is immutable. Create a new instance instead."
            )
        # Assign a slug on create when one wasn't set explicitly. bulk_create
        # skips save(), so those paths must use the manager's mint_many() — see
        # CitationInstanceManager. A (vanishingly rare) collision here surfaces
        # as IntegrityError; the bulk path additionally retries under a savepoint.
        if not self.slug:
            self.slug = generate_citation_slug()
        # save() is the one chokepoint that sees every explicit slug: the API and
        # field-evidence paths call full_clean(exclude=["slug"]) (slug isn't set
        # yet there) and bulk_create skips save() entirely, so a field-level
        # validator would never fire. Validating here covers explicit slugs and
        # re-checks the generated one for free; bulk leans on the generator plus
        # the DB length CHECK.
        validate_citation_slug(self.slug)
        super().save(*args, **kwargs)
