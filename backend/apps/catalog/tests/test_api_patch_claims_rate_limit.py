"""Edit-bucket rate-limit coverage for PATCH /api/.../claims/ routes.

The CREATE and DELETE buckets are exercised by per-entity create/delete test
files. This file pins the third bucket — EDIT — across the three PATCH-claim
wiring surfaces in use today:

* a per-module hand-written route (Title)
* a second per-module hand-written route (Person)
* the shared ``_patch_taxonomy`` helper backing the 9 taxonomy routes (Tag)

A wiring miss in any one surface (forgetting the rate-limit gate or the 429
response entry) would silently pass without these.

Each test pre-fills the edit bucket with ``check_and_record`` so we only make
one real HTTP PATCH per test instead of 61 — EDIT's limit of 60 makes raw
repetition impractical.

Staff exemption is not re-tested here. ``check_and_record``'s exempt-user
short-circuit is covered at the unit level in
``apps/provenance/tests/test_rate_limits.py::test_staff_bypass``, and the
three 429 tests below prove the route actually calls ``check_and_record``
(otherwise they would 200 rather than 429).
"""

from __future__ import annotations

import json

import pytest

from apps.catalog.models import Tag, Title
from apps.core.types import JsonBody
from apps.provenance.constants import EDIT_RATE_LIMIT
from apps.provenance.rate_limits import EDIT_RATE_LIMIT_SPEC, check_and_record
from apps.provenance.test_factories import make_claim


def _fill_edit_bucket(user) -> None:
    for _ in range(EDIT_RATE_LIMIT):
        check_and_record(user, EDIT_RATE_LIMIT_SPEC)


def _patch(client, url: str, body: JsonBody):
    return client.patch(url, data=json.dumps(body), content_type="application/json")


def _assert_429_edit(resp) -> None:
    assert resp.status_code == 429, resp.content
    assert int(resp.headers["Retry-After"]) >= 1
    detail = resp.json()["detail"]
    assert detail["kind"] == "rate_limit"
    assert detail["bucket"] == "edit"
    assert detail["retry_after"] >= 1


@pytest.fixture
def title(db, bootstrap_source):
    t = Title.objects.create(name="Medieval Madness", slug="medieval-madness")
    make_claim(t, "name", "Medieval Madness", ingest_source=bootstrap_source)
    return t


@pytest.fixture
def tag(db):
    return Tag.objects.create(name="Widebody", slug="widebody")


@pytest.mark.django_db
class TestPatchClaimsEditRateLimit:
    def test_title_patch_429_when_edit_bucket_full(self, client, user, title):
        client.force_login(user)
        _fill_edit_bucket(user)
        resp = _patch(
            client,
            f"/api/titles/{title.slug}/claims/",
            {"fields": {"description": "Over limit."}},
        )
        _assert_429_edit(resp)

    def test_person_patch_429_when_edit_bucket_full(self, client, user, person):
        client.force_login(user)
        _fill_edit_bucket(user)
        resp = _patch(
            client,
            f"/api/people/{person.slug}/claims/",
            {"fields": {"description": "Over limit."}},
        )
        _assert_429_edit(resp)

    def test_taxonomy_patch_429_when_edit_bucket_full(self, client, user, tag):
        """Covers all 9 taxonomy PATCH routes via the shared ``_patch_taxonomy``."""
        client.force_login(user)
        _fill_edit_bucket(user)
        resp = _patch(
            client,
            f"/api/tags/{tag.slug}/claims/",
            {"fields": {"description": "Over limit."}},
        )
        _assert_429_edit(resp)
