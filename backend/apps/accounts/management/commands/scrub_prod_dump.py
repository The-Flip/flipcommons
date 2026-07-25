"""Scrub user PII out of a restored production dump, and keep dev logins working.

Run by ``scripts/prod-to-sqlite.sh`` against the local Postgres container holding the
freshly-restored prod dump, *before* ``dumpdata`` hands the data on to the local
SQLite dev DB.

Running before ``dumpdata`` keeps PII out of everything that outlives the run, and
keeps the ``--natural-foreign`` references self-consistent — ``User.natural_key()``
is ``(email,)``, so the dump's FK references are generated from the scrubbed
addresses. It does not make the container it runs against clean: a logical scrub
leaves the originals in storage, which is why the script discards that container
rather than keeping it (its header explains).

Three jobs:

1. Every non-consenting user is scrubbed — email, name, password hash and WorkOS
   link. Rows are never deleted: provenance and ``Actor`` FKs depend on them, and
   the username is the public identity (``/users/<username>``), not PII.

2. Every session is deleted. ``session_data`` carries the pending-signup payload
   — email, first and last name — in cleartext, and a production session is
   useless against a local dev site.

3. The consenting developers' WorkOS link is carried forward from the db.sqlite3
   being replaced. Prod's ``workos_user_id`` values belong to the *prod* WorkOS
   environment and can never match what a local sign-in returns, so importing
   them unchanged locks the developer out: the id lookup misses, the email
   lookup finds an active row bound to a different id, and
   ``workos_match._refuse_active_email_collision`` refuses the login. Replacing
   them with the ids from the outgoing local DB makes the first branch match on
   the very next sign-in.
"""

from __future__ import annotations

import argparse
import sqlite3
from contextlib import closing
from enum import Enum, auto
from pathlib import Path
from typing import Any, Final, NamedTuple, assert_never

from django.contrib.auth.hashers import make_password
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.models import Value
from django.db.models.functions import Concat

from apps.accounts.models import User
from apps.accounts.types import Username, WorkOsUserId

DEV_USERNAMES: Final[frozenset[Username]] = frozenset({"moses", "william"})
"""Developers who have consented to their own PII surviving the copy.

Consent is per-person and recorded here deliberately, in git, where it can be
reviewed and revoked. Usernames are public identifiers, not PII. Anyone not on
this list is scrubbed.
"""

SCRUBBED_EMAIL_DOMAIN: Final[str] = "users.invalid"
"""RFC 2606 reserved TLD — guarantees a scrubbed address can never route mail."""


class DeveloperOutcome(Enum):
    """What ``_restore_developer`` did to one row."""

    RELINKED = auto()
    """WorkOS link carried forward; the row keeps its admin rights."""
    UNLINKED = auto()
    """No id to carry forward; the row was unlinked and de-privileged."""
    ABSENT = auto()
    """No such user in the dump — nothing to do."""


class ScrubReport(NamedTuple):
    """What ``handle`` did, for the operator-facing summary."""

    scrubbed: int
    sessions_deleted: int
    relinked: list[Username]
    unlinked: list[Username]


# Postgres HOST is "" when connecting over a local unix socket.
_LOCAL_HOSTS: Final[frozenset[str]] = frozenset({"", "localhost", "127.0.0.1", "::1"})


def _assert_local_database() -> None:
    """Refuse to run against anything but a local database.

    The command rewrites every user row, so this is the substantive protection
    against it being pointed somewhere real — an inherited ``DATABASE_URL``, a
    stray ``railway run``. It checks where the connection *points*, not what is
    on the other end, so a port-forwarded tunnel to a remote database would
    still pass; treat it as a guard against accidents, not against intent.
    """
    # django-stubs types settings_dict as dict[str, Any]; annotate on the way out
    # so the checks below run against known types.
    settings_dict = connections[DEFAULT_DB_ALIAS].settings_dict
    engine: str = settings_dict["ENGINE"]
    # SQLite is a local file by construction, and is what the test suite runs on.
    if "sqlite" in engine:
        return
    configured_host: object = settings_dict.get("HOST")
    host = str(configured_host or "").lower()
    if host not in _LOCAL_HOSTS:
        raise CommandError(
            f"refusing to scrub a non-local database (host {host!r}). "
            "This command rewrites every user row and is only ever meant to "
            "run against the local Postgres container in scripts/prod-to-sqlite.sh."
        )


def _carried_workos_ids(db_path: Path) -> dict[Username, WorkOsUserId]:
    """Read ``username -> workos_user_id`` for the dev users out of a SQLite file.

    Opened read-only: this is the database the caller is about to replace, and a
    failed read must never be able to damage it. Any missing file, missing table
    or otherwise unreadable DB yields ``{}`` — the caller degrades to unlinking
    the developers rather than failing a rebuild that has already pulled prod
    down over the network.
    """
    if not db_path.is_file():
        return {}
    found: dict[Username, WorkOsUserId] = {}
    try:
        # closing(), not a bare `with`: sqlite3's connection context manager
        # scopes the *transaction*, not the handle, and a leaked handle only
        # shows up much later as an unraisable ResourceWarning.
        with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as conn:
            # One static query per name keeps the SQL a literal rather than a
            # built IN clause. sqlite3 returns Any out of what is an arbitrary
            # file, so the column is taken as `object` and coerced.
            for username in sorted(DEV_USERNAMES):
                row: tuple[object, ...] | None = conn.execute(
                    "SELECT workos_user_id FROM accounts_user WHERE username = ?",
                    (username,),
                ).fetchone()
                if row is not None and row[0]:
                    found[username] = str(row[0])
    except sqlite3.Error:
        return {}
    return found


class Command(BaseCommand):
    help = (
        "Scrub user PII from a restored prod dump and carry dev WorkOS links forward."
    )

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--carry-forward-from",
            metavar="SQLITE_PATH",
            help=(
                "Existing db.sqlite3 to read the developers' local WorkOS ids "
                "from. If omitted or unreadable, they are unlinked instead."
            ),
        )

    def handle(
        self,
        *args: object,
        **options: Any,  # noqa: ANN401 - argparse-driven Django command kwargs
    ) -> None:
        _assert_local_database()

        # argparse hands back Any; pin it so nothing downstream is typed off it.
        source: str | None = options["carry_forward_from"]
        carried = _carried_workos_ids(Path(source)) if source else {}

        scrubbed = self._scrub_others()
        sessions_deleted = self._drop_sessions()
        relinked: list[Username] = []
        unlinked: list[Username] = []
        for username in sorted(DEV_USERNAMES):
            outcome = self._restore_developer(username, carried.get(username))
            match outcome:
                case DeveloperOutcome.RELINKED:
                    relinked.append(username)
                case DeveloperOutcome.UNLINKED:
                    unlinked.append(username)
                case DeveloperOutcome.ABSENT:
                    pass
                case _:
                    # Exhaustiveness is checker-enforced: a new DeveloperOutcome
                    # member fails mypy here instead of being silently dropped.
                    assert_never(outcome)

        self._report(
            ScrubReport(
                scrubbed=scrubbed,
                sessions_deleted=sessions_deleted,
                relinked=relinked,
                unlinked=unlinked,
            )
        )

    def _drop_sessions(self) -> int:
        """Delete every session row. Returns how many went.

        Dropped rather than scrubbed: ``session_data`` holds the pending-signup
        payload — email, first and last name — in cleartext, and a production
        session authenticates nobody against a local dev site.

        Excluding them at ``dumpdata`` time protects db.sqlite3 only; they would
        otherwise stay in the Postgres the script snapshots and keeps.
        """
        deleted, _by_label = Session.objects.all().delete()
        return deleted

    def _scrub_others(self) -> int:
        """Blank the PII on every non-developer row. Returns the row count.

        A single UPDATE rather than a Python loop: ``Concat`` builds each
        replacement address in SQL, and ``.update()`` bypasses ``save()`` so
        ``ActorModel``'s Actor sync doesn't fire — nothing scrubbed here is
        mirrored onto ``Actor`` anyway.

        Every scrubbed address is ``<username>@users.invalid``, which satisfies the
        not-blank CHECK and is unique for free under the ``Lower("email")``
        constraint, since usernames are unique and lowercase by policy.
        """
        return User.objects.exclude(username__in=DEV_USERNAMES).update(
            email=Concat("username", Value(f"@{SCRUBBED_EMAIL_DOMAIN}")),
            first_name="",
            last_name="",
            # One unusable hash shared by every row; unusable passwords never
            # validate whatever their value.
            password=make_password(None),
            workos_user_id=None,
        )

    def _restore_developer(
        self, username: Username, workos_user_id: WorkOsUserId | None
    ) -> DeveloperOutcome:
        """Re-link one developer's account to their *local* WorkOS identity.

        With an id carried forward, the row keeps its admin rights and the next
        sign-in matches on the id directly. Without one, the row must be left
        *both* unlinked and unprivileged: ``workos_match`` refuses to auto-link a
        privileged row by email, so leaving is_staff on would swap one lockout
        for another. The operator re-grants with ``grant_admin`` after signing in.
        """
        linked = workos_user_id is not None
        # update() reports rows touched, so "no such developer" falls out of the write.
        updated = User.objects.filter(username=username).update(
            workos_user_id=workos_user_id,
            is_staff=linked,
            is_superuser=linked,
        )
        if not updated:
            return DeveloperOutcome.ABSENT
        return DeveloperOutcome.RELINKED if linked else DeveloperOutcome.UNLINKED

    def _report(self, report: ScrubReport) -> None:
        self.stdout.write(
            f"Scrubbed PII from {report.scrubbed} user(s); "
            f"exempted {', '.join(sorted(DEV_USERNAMES))}."
        )
        self.stdout.write(f"Deleted {report.sessions_deleted} session(s).")
        if report.relinked:
            self.stdout.write(
                f"Carried local WorkOS link forward for: {', '.join(report.relinked)}."
            )
        for username in report.unlinked:
            self.stderr.write(
                self.style.WARNING(
                    f"No local WorkOS id found for {username!r} — the account was "
                    "unlinked and admin rights removed so the next sign-in can "
                    "re-link it. Sign in at http://localhost:5173, then run "
                    "`manage.py grant_admin <email>` to restore admin."
                )
            )
