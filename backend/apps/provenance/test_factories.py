"""Test-only factories for provenance models.

Kept outside ``tests/`` so test helpers can be imported across apps
without circular dependencies or duplicated conftest fixtures.

Use these in tests instead of calling ``ChangeSet.objects.create`` directly.
They encode the attribution invariants (every ChangeSet carries an actor;
action iff interactive/non-ingest) so mistakes fail at call time rather than
at constraint time.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Literal

from apps.accounts.models import User
from apps.citation.models import CitationInstance
from apps.citation.test_factories import make_citation_source
from apps.core.types import ClaimFieldName, ClaimKey

from .changeset_writer import record_changeset
from .claim_writer import _assert_claim
from .models import (
    ChangeSet,
    ChangeSetAction,
    ClaimCitationInstance,
    IngestRun,
    Source,
)

if TYPE_CHECKING:
    from apps.citation.models import CitationSource
    from apps.core.models import License

    from .models import Claim, ClaimControlledModel


def make_claim(
    subject: ClaimControlledModel,
    field_name: ClaimFieldName,
    value: object,
    *,
    ingest_source: Source | None = None,
    user: User | None = None,
    claim_key: ClaimKey = "",
    license: License | None = None,
    changeset: ChangeSet | None = None,
) -> Claim:
    """Mint a claim through the single write primitive, for tests.

    A drop-in for the old ``Claim.objects.assert_claim``: same ``user=`` /
    ingest ``source=`` signature. Attribution now rides on a ChangeSet's actor, so when
    no ``changeset`` is supplied this auto-creates the attributing one (user →
    ``user_changeset``; source → ``source_changeset``) and threads it into the
    actor-first primitive. The factory is the single seam the call sites target.
    """
    if user is not None and ingest_source is not None:
        raise ValueError("make_claim: pass at most one of user= or source=.")
    if changeset is None:
        if user is not None:
            changeset = user_changeset(user)
        elif ingest_source is not None:
            changeset = source_changeset(ingest_source)
        else:
            raise ValueError("Provide a source, a user, or a changeset.")
    else:
        # A user=/source= passed alongside an explicit changeset is redundant —
        # attribution rides on changeset.actor, not these args. Guard that the
        # one supplied (if any) agrees, so a mismatched pair fails loudly here
        # (the cross-check the old assert_claim enforced) instead of silently
        # attributing to the changeset's actor.
        attributed = user if user is not None else ingest_source
        if attributed is not None and changeset.actor_id != attributed.actor_id:
            raise ValueError(
                "make_claim: changeset.actor does not match the given user=/source=."
            )
    return _assert_claim(
        subject,
        field_name,
        value,
        changeset=changeset,
        claim_key=claim_key,
        license=license,
    )


# Mirrors the ingest Source model's SourceType choices — a Literal so a bad source_type
# fails at type-check. Constraint tests that need an invalid value build an ingest Source
# directly.
type IngestSourceTypeValue = Literal["database", "wiki", "book", "editorial", "other"]


def make_ingest_source(
    *,
    name: str | None = None,
    source_type: IngestSourceTypeValue = "database",
    priority: int = 0,
    slug: str = "",
    url: str = "",
    description: str = "",
    is_enabled: bool = True,
    default_license: License | None = None,
) -> Source:
    """Create a provenance ingest ``Source`` for tests, defaulting the name.

    Every field mirrors the model's own default (``priority=0`` included), so
    this is a faithful drop-in for ``Source.objects.create`` — it injects no
    opinion the model doesn't. ``slug`` auto-fills from ``name`` when left blank;
    the backing ``Actor`` is minted by ``ActorModel.save()``. The default name is
    uuid-suffixed so repeated bare calls don't trip the case-insensitive
    unique-name constraint — pass ``name=`` when a test asserts on a specific
    name or priority ordering.
    """
    if name is None:
        name = f"Test Source {uuid.uuid4().hex[:8]}"
    return Source.objects.create(
        name=name,
        source_type=source_type,
        priority=priority,
        slug=slug,
        url=url,
        description=description,
        is_enabled=is_enabled,
        default_license=default_license,
    )


def make_citation_instance(
    *,
    citation_source: CitationSource | None = None,
    locator: str = "",
    quote: str = "",
    slug: str = "",
) -> CitationInstance:
    """Create a ``CitationInstance`` for tests, auto-providing a citation source.

    Yields a floating instance — shared evidence nothing references yet.
    ``slug`` auto-fills when left blank. To attach it to a claim as supporting
    evidence, prefer :func:`cite_claim`, which also writes the join row.
    """
    return CitationInstance.objects.create(
        citation_source=citation_source or make_citation_source(),
        locator=locator,
        quote=quote,
        slug=slug,
    )


def cite_claim(
    claim: Claim,
    *,
    citation_source: CitationSource | None = None,
    locator: str = "",
) -> CitationInstance:
    """Attach a citation instance to *claim* as supporting evidence.

    The intent-revealing "this claim is backed by this evidence" helper: it
    mints the instance and links it to the claim through a
    ``ClaimCitationInstance`` join row — the channel every read path resolves,
    and (as of the shared-evidence write path) the only tie a scalar cite has
    to its claims. Returns the created instance.
    """
    instance = make_citation_instance(citation_source=citation_source, locator=locator)
    claim_citation_instance(claim, instance)
    return instance


def claim_citation_instance(
    claim: Claim, citation_instance: CitationInstance
) -> ClaimCitationInstance:
    """Create a claim <-> citation-instance support edge for tests."""
    return ClaimCitationInstance.objects.create(
        claim=claim, citation_instance=citation_instance
    )


def ingest_run(
    source: Source,
    *,
    input_fingerprint: str = "sha256:test",
    patch_id: str | None = None,
) -> IngestRun:
    """Create an ``IngestRun`` for tests that need one as incidental scaffolding.

    Tests asserting ``IngestRun``'s own constraints/lifecycle should construct
    it directly with the specific fields under test instead of using this.
    """
    return IngestRun.objects.create(
        source=source, input_fingerprint=input_fingerprint, patch_id=patch_id
    )


def user_changeset(
    user: User,
    *,
    action: ChangeSetAction = ChangeSetAction.EDIT,
    note: str = "",
) -> ChangeSet:
    """Create a user-attributed ChangeSet for tests.

    Defaults to ``action=EDIT`` since that's what every pre-create test
    fixture was implicitly asserting. Callers testing create/delete/revert
    paths pass the matching action explicitly. Routed through
    ``record_changeset`` so every fixture ChangeSet carries an actor.
    """
    return record_changeset(actor=user.actor, action=action, note=note)


def ingest_changeset(ingest_run: IngestRun, *, note: str = "") -> ChangeSet:
    """Create an ingest-attributed ChangeSet for tests.

    Ingest ChangeSets never carry an action — that column is reserved for
    user-driven changes (see ``ChangeSet`` check constraints). Routed through
    ``record_changeset`` so the actor invariant is encoded in one place.
    """
    return record_changeset(
        actor=ingest_run.source.actor, ingest_run=ingest_run, note=note
    )


def source_changeset(source: Source, *, note: str = "") -> ChangeSet:
    """Create a source-attributed ChangeSet for tests.

    A source can only attribute a ChangeSet through an ``IngestRun`` (the
    ChangeSet user-XOR-ingest_run constraint), so this mints a throwaway
    ``IngestRun`` for the source and returns an ingest ChangeSet linked to it.
    Use it when a test needs a source-attributed claim minted through
    ``make_claim`` without hand-building the run.
    """
    run = ingest_run(source, input_fingerprint="test-source-changeset")
    return ingest_changeset(run, note=note)
