"""Tests for the ``scrub_prod_dump`` management command."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from io import StringIO
from pathlib import Path

import pytest
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DEFAULT_DB_ALIAS, connections

from apps.accounts.management.commands.scrub_prod_dump import DEV_USERNAMES
from apps.accounts.models import User
from apps.accounts.pending import PENDING_SESSION_KEY
from apps.accounts.test_factories import make_user


def _run(carry_forward_from: Path | None = None) -> tuple[str, str]:
    """Call the command, returning its (stdout, stderr)."""
    out, err = StringIO(), StringIO()
    args = (
        ["--carry-forward-from", str(carry_forward_from)]
        if carry_forward_from is not None
        else []
    )
    call_command("scrub_prod_dump", *args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


def _old_dev_db(tmp_path: Path, rows: dict[str, str | None]) -> Path:
    """Write a minimal stand-in for the db.sqlite3 being replaced."""
    path = tmp_path / "db.sqlite3"
    conn = sqlite3.connect(path)
    # `closing` closes the handle; the bare `conn` commits. sqlite3's own
    # context manager only does the latter.
    with closing(conn), conn:
        conn.execute("CREATE TABLE accounts_user (username TEXT, workos_user_id TEXT)")
        conn.executemany(
            "INSERT INTO accounts_user VALUES (?, ?)",
            list(rows.items()),
        )
    return path


# --- scrubbing ---------------------------------------------------------------


@pytest.mark.django_db
def test_scrubs_pii_from_a_regular_user():
    make_user(
        username="stranger",
        email="Real.Person@gmail.com",
        first_name="Real",
        last_name="Person",
        workos_user_id="user_prod_stranger",
    )

    _run()

    user = User.objects.get(username="stranger")
    assert user.email == "stranger@users.invalid"
    assert user.first_name == ""
    assert user.last_name == ""
    assert user.workos_user_id is None
    assert not user.has_usable_password()


@pytest.mark.django_db
def test_keeps_username_and_timestamps():
    """Username is public identity, not PII; timestamps are left alone by choice."""
    user = make_user(username="stranger", email="real@gmail.com")
    joined, last_seen = user.date_joined, user.last_seen_at

    _run()

    user.refresh_from_db()
    assert user.username == "stranger"
    assert user.date_joined == joined
    assert user.last_seen_at == last_seen
    assert user.is_active


@pytest.mark.django_db
def test_rows_are_never_deleted():
    """Provenance and Actor FKs depend on the rows surviving."""
    for i in range(3):
        make_user(username=f"stranger-{i}", email=f"p{i}@gmail.com")

    out, _ = _run()

    assert User.objects.count() == 3
    assert "Scrubbed PII from 3 user(s)" in out


@pytest.mark.django_db
def test_scrubbed_emails_stay_unique_and_valid():
    """<username>@users.invalid inherits uniqueness from the unique username."""
    make_user(username="alpha", email="same-person@gmail.com")
    make_user(username="beta", email="Same-Person+alias@gmail.com")

    _run()

    assert set(User.objects.values_list("email", flat=True)) == {
        "alpha@users.invalid",
        "beta@users.invalid",
    }


@pytest.mark.django_db
def test_consenting_developers_are_not_scrubbed(tmp_path):
    make_user(
        username="moses",
        email="moses@tacocat.com",
        first_name="Dean",
        last_name="Moses",
        workos_user_id="user_prod_moses",
    )

    _run(_old_dev_db(tmp_path, {"moses": "user_local_moses"}))

    user = User.objects.get(username="moses")
    assert user.email == "moses@tacocat.com"
    assert user.first_name == "Dean"
    assert user.last_name == "Moses"


# --- sessions ----------------------------------------------------------------


@pytest.mark.django_db
def test_deletes_every_session():
    """Excluding them from dumpdata protects db.sqlite3 only.

    The Postgres this runs against is snapshotted and kept afterwards, so the
    rows have to actually go.
    """
    for _ in range(3):
        SessionStore().create()
    assert Session.objects.count() == 3

    out, _ = _run()

    assert Session.objects.count() == 0
    assert "Deleted 3 session(s)" in out


@pytest.mark.django_db
def test_deletes_the_session_carrying_signup_pii():
    """``session_data`` holds the pending-signup payload in cleartext."""
    store = SessionStore()
    store[PENDING_SESSION_KEY] = {
        "email": "real.person@gmail.com",
        "first_name": "Real",
        "last_name": "Person",
    }
    store.create()
    key = store.session_key
    assert key is not None

    _run()

    assert not Session.objects.filter(session_key=key).exists()


@pytest.mark.django_db
def test_session_delete_is_reported_when_there_are_none():
    out, _ = _run()

    assert "Deleted 0 session(s)" in out


# --- carrying the developer WorkOS link forward ------------------------------


@pytest.mark.django_db
def test_carries_local_workos_id_forward_and_keeps_admin(tmp_path):
    """The prod-environment id is replaced by the one the local IdP will send."""
    make_user(
        username="moses",
        email="moses@tacocat.com",
        workos_user_id="user_prod_moses",
        is_staff=False,
        is_superuser=False,
    )

    out, err = _run(_old_dev_db(tmp_path, {"moses": "user_local_moses"}))

    user = User.objects.get(username="moses")
    assert user.workos_user_id == "user_local_moses"
    assert user.is_staff
    assert user.is_superuser
    assert "Carried local WorkOS link forward for: moses" in out
    assert err == ""


@pytest.mark.django_db
def test_ignores_non_developer_rows_in_the_old_db(tmp_path):
    """Only the consented usernames are read out of the outgoing DB."""
    make_user(username="stranger", email="real@gmail.com")

    _run(_old_dev_db(tmp_path, {"stranger": "user_local_stranger"}))

    assert User.objects.get(username="stranger").workos_user_id is None


@pytest.mark.django_db
def test_unlinks_and_deprivileges_when_no_id_can_be_carried(tmp_path):
    """A privileged row with a null link is refused auto-link by workos_match.

    So "no id to carry" has to clear is_staff/is_superuser as well, or the next
    sign-in trades the account_conflict lockout for the privileged-row one.
    """
    make_user(
        username="moses",
        email="moses@tacocat.com",
        workos_user_id="user_prod_moses",
        is_staff=True,
        is_superuser=True,
    )

    _out, err = _run(_old_dev_db(tmp_path, {}))

    user = User.objects.get(username="moses")
    assert user.workos_user_id is None
    assert not user.is_staff
    assert not user.is_superuser
    assert "No local WorkOS id found for 'moses'" in err
    assert "grant_admin" in err


@pytest.mark.django_db
def test_null_workos_id_in_old_db_counts_as_no_id(tmp_path):
    make_user(username="moses", email="moses@tacocat.com", workos_user_id="user_prod")

    _out, err = _run(_old_dev_db(tmp_path, {"moses": None}))

    assert User.objects.get(username="moses").workos_user_id is None
    assert "No local WorkOS id found for 'moses'" in err


@pytest.mark.django_db
def test_missing_old_db_degrades_instead_of_failing(tmp_path):
    """A first-ever run has no outgoing DB; the rebuild must still complete."""
    make_user(username="moses", email="moses@tacocat.com", workos_user_id="user_prod")

    _out, err = _run(tmp_path / "does-not-exist.sqlite3")

    assert User.objects.get(username="moses").workos_user_id is None
    assert "No local WorkOS id found for 'moses'" in err


@pytest.mark.django_db
def test_unreadable_old_db_degrades_instead_of_failing(tmp_path):
    """A pre-migration or corrupt DB has no accounts_user table to read."""
    make_user(username="moses", email="moses@tacocat.com", workos_user_id="user_prod")
    junk = tmp_path / "db.sqlite3"
    junk.write_text("not a database")

    _out, err = _run(junk)

    assert User.objects.get(username="moses").workos_user_id is None
    assert "No local WorkOS id found for 'moses'" in err


@pytest.mark.django_db
def test_absent_developer_is_silently_skipped(tmp_path):
    """Not every dump contains every developer."""
    make_user(username="stranger", email="real@gmail.com")

    _out, err = _run(_old_dev_db(tmp_path, {"moses": "user_local_moses"}))

    assert err == ""
    assert not User.objects.filter(username__in=DEV_USERNAMES).exists()


# --- guard -------------------------------------------------------------------


@pytest.mark.django_db
def test_refuses_a_remote_database():
    settings_dict = connections[DEFAULT_DB_ALIAS].settings_dict
    remote = {
        **settings_dict,
        "ENGINE": "django.db.backends.postgresql",
        "HOST": "containers-us-west-1.railway.app",
    }
    make_user(username="stranger", email="real@gmail.com")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            connections[DEFAULT_DB_ALIAS], "settings_dict", remote, raising=False
        )
        with pytest.raises(
            CommandError, match="refusing to scrub a non-local database"
        ):
            call_command("scrub_prod_dump", stdout=StringIO(), stderr=StringIO())

    assert User.objects.get(username="stranger").email == "real@gmail.com"


@pytest.mark.django_db
def test_allows_a_loopback_postgres():
    """The local Postgres container the script actually targets."""
    settings_dict = connections[DEFAULT_DB_ALIAS].settings_dict
    local_pg = {
        **settings_dict,
        "ENGINE": "django.db.backends.postgresql",
        "HOST": "127.0.0.1",
    }
    make_user(username="stranger", email="real@gmail.com")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            connections[DEFAULT_DB_ALIAS], "settings_dict", local_pg, raising=False
        )
        call_command("scrub_prod_dump", stdout=StringIO(), stderr=StringIO())

    assert User.objects.get(username="stranger").email == "stranger@users.invalid"
