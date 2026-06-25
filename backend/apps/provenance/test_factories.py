"""Test-only factories for provenance models.

Kept outside ``tests/`` so test helpers can be imported across apps
without circular dependencies or duplicated conftest fixtures.

Use these in tests instead of calling ``ChangeSet.objects.create`` directly.
They encode invariants the DB enforces (user XOR ingest_run; action iff
user) so mistakes fail at call time rather than at constraint time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from apps.accounts.models import User

from .changeset_writer import record_changeset
from .claim_writer import _assert_claim
from .models import ChangeSet, ChangeSetAction, IngestRun

if TYPE_CHECKING:
    from apps.core.models import License

    from .models import Claim, ClaimControlledModel, Source


def make_claim(
    subject: ClaimControlledModel,
    field_name: str,
    value: object,
    citation: str = "",
    *,
    source: Source | None = None,
    user: User | None = None,
    claim_key: str = "",
    license: License | None = None,
    changeset: ChangeSet | None = None,
) -> Claim:
    """Mint a claim through the single write primitive, for tests.

    A drop-in for the old ``Claim.objects.assert_claim``: same ``user=`` /
    ``source=`` signature. Attribution now rides on a ChangeSet's actor, so when
    no ``changeset`` is supplied this auto-creates the attributing one (user →
    ``user_changeset``; source → ``source_changeset``) and threads it into the
    actor-first primitive. The factory is the single seam the call sites target.
    """
    if changeset is None:
        if user is not None and source is None:
            changeset = user_changeset(user)
        elif source is not None and user is None:
            changeset = source_changeset(source)
        else:
            raise ValueError("Provide exactly one of source or user (or a changeset).")
    return _assert_claim(
        subject,
        field_name,
        value,
        citation,
        changeset=changeset,
        claim_key=claim_key,
        license=license,
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
    action: ChangeSetAction | str = ChangeSetAction.EDIT,
    note: str = "",
) -> ChangeSet:
    """Create a user-attributed ChangeSet for tests.

    Defaults to ``action=EDIT`` since that's what every pre-create test
    fixture was implicitly asserting. Callers testing create/delete/revert
    paths pass the matching action explicitly. Routed through
    ``record_changeset`` so every fixture ChangeSet carries an actor.
    """
    return record_changeset(actor=user.actor, action=ChangeSetAction(action), note=note)


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
