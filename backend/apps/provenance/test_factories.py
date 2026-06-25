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

    A behavior-identical drop-in for the old ``Claim.objects.assert_claim``: same
    arguments, same semantics (user claims still require a ``changeset``; source
    claims may omit one). The factory exists so tests target a single seam — when
    the primitive goes actor-first, only this function changes, not the call
    sites. ``source_changeset`` / ``user_changeset`` remain available for callers
    that want to mint the attributing ChangeSet explicitly.
    """
    return _assert_claim(
        subject,
        field_name,
        value,
        citation,
        source=source,
        user=user,
        claim_key=claim_key,
        license=license,
        changeset=changeset,
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
    paths pass the matching action explicitly.
    """
    return ChangeSet.objects.create(user=user, action=action, note=note)


def ingest_changeset(ingest_run: IngestRun, *, note: str = "") -> ChangeSet:
    """Create an ingest-attributed ChangeSet for tests.

    Ingest ChangeSets never carry an action — that column is reserved for
    user-driven changes (see ``ChangeSet`` check constraints).
    """
    return ChangeSet.objects.create(ingest_run=ingest_run, note=note)


def source_changeset(source: Source, *, note: str = "") -> ChangeSet:
    """Create a source-attributed ChangeSet for tests.

    A source can only attribute a ChangeSet through an ``IngestRun`` (the
    ChangeSet user-XOR-ingest_run constraint), so this mints a throwaway
    ``IngestRun`` for the source and returns an ingest ChangeSet linked to it.
    Use it when a test needs a source-attributed claim minted through
    ``make_claim`` without hand-building the run.
    """
    run = IngestRun.objects.create(
        source=source, input_fingerprint="test-source-changeset"
    )
    return ingest_changeset(run, note=note)
