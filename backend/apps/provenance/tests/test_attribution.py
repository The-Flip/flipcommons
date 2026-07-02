"""Unit tests for the actor → backing-record attribution accessors.

Pins that ``actor_author`` / ``source_backing`` / ``actor_user`` /
``actor_user_id`` route by ``Actor.backing_model`` to the right backing record
for both v1 actor types (user, source), the single model-driven dispatch the
current attribution readers rely on.
"""

from __future__ import annotations

import pytest

from apps.accounts.test_factories import make_user
from apps.provenance.attribution import actor_user, actor_user_id, source_backing
from apps.provenance.helpers import actor_author
from apps.provenance.schemas import ClaimSourceAuthorSchema, ClaimUserAuthorSchema
from apps.provenance.test_factories import make_ingest_source

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return make_user(email="ada@example.com", username="ada", password="x")


@pytest.fixture
def source():
    return make_ingest_source(name="OPDB", source_type="database", priority=5)


def test_actor_author_user(user):
    author = actor_author(user.actor)
    assert isinstance(author, ClaimUserAuthorSchema)
    assert author.username == "ada"


def test_actor_author_source(source):
    author = actor_author(source.actor)
    assert isinstance(author, ClaimSourceAuthorSchema)
    assert author.name == "OPDB"


def test_source_backing_routes_by_type(user, source):
    assert source_backing(source.actor) == source
    assert source_backing(user.actor) is None
    assert source_backing(None) is None


def test_actor_user_routes_by_type(user, source):
    assert actor_user(user.actor) == user
    assert actor_user(source.actor) is None
    assert actor_user(None) is None


def test_actor_user_id_routes_by_type(user, source):
    assert actor_user_id(user.actor) == user.pk
    assert actor_user_id(source.actor) is None
    assert actor_user_id(None) is None
