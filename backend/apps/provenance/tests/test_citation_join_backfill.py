"""Guards for the scalar-citation join backfill migration (0018).

0018 backfills a ``ClaimCitationInstance`` self-link per scalar
``CitationInstance`` (``claim`` set), then collapses the per-ChangeSet clones the
old write path minted -- keep one survivor per ``(changeset, source, locator)``,
repoint the group's join rows, delete the losers.

These build the pre-collapse shape (scalar instances with ``claim`` set and no
join rows, plus the broken shapes the fail-fast checks catch). ``CitationInstance``
reads ``claim`` directly, which CON2 later drops -- so rather than construct rows
on a schema that will lose the column, they run against the frozen state at
provenance 0017 (the node 0018 builds on) via :func:`historical_apps`, where the
FK still exists. The reconstructed historical models have no ``save()`` hook, so
each instance's ``slug`` is assigned by hand.
"""

from __future__ import annotations

import importlib

import pytest

from apps.provenance.test_migration_state import historical_apps

_migration = importlib.import_module(
    "apps.provenance.migrations.0018_backfill_scalar_citation_joins"
)

# Pin provenance at 0017 (the node 0018 builds on). citation and core are pinned
# at their leaves too: provenance/0017's own dependency closure references an early
# citation state (created_by → User, pre-Actor) and doesn't reach core at all, but
# the DB citation table is at its leaf and the collapse reads core.RecordReference
# -- so name both leaves to keep the frozen registry consistent with the schema.
_BEFORE = (
    ("provenance", "0017_claimcitationinstance"),
    ("citation", "0012_tighten_attribution_not_null"),
    ("core", "0001_initial"),
)

_CONS = "bcdfghjklmnpqrstvwxyz"


def _slug(i: int) -> str:
    """A unique, valid 8-consonant citation slug from an index."""
    out = ""
    for _ in range(8):
        out = _CONS[i % len(_CONS)] + out
        i //= len(_CONS)
    return out


class _Build:
    """Frozen-state row builders sharing one actor / source / content type."""

    def __init__(self, apps):
        self.apps = apps
        Actor = apps.get_model("actors", "Actor")
        self.actor = Actor.objects.create(
            backing_model="source", priority=1000, resolution_status="active"
        )
        ContentType = apps.get_model("contenttypes", "ContentType")
        self.ct, _ = ContentType.objects.get_or_create(
            app_label="catalog", model="manufacturer"
        )
        CitationSource = apps.get_model("citation", "CitationSource")
        self.source = CitationSource.objects.create(
            name="The Encyclopedia of Pinball",
            source_type="book",
            created_by=self.actor,
            updated_by=self.actor,
        )
        self._slug_seq = 0

    def source2(self):
        CitationSource = self.apps.get_model("citation", "CitationSource")
        return CitationSource.objects.create(
            name="Another Work",
            source_type="book",
            created_by=self.actor,
            updated_by=self.actor,
        )

    def changeset(self):
        ChangeSet = self.apps.get_model("provenance", "ChangeSet")
        return ChangeSet.objects.create(actor=self.actor, action="edit")

    def claim(self, changeset, *, object_id=1, key="name"):
        Claim = self.apps.get_model("provenance", "Claim")
        return Claim.objects.create(
            content_type=self.ct,
            object_id=object_id,
            actor=self.actor,
            field_name=key,
            claim_key=key,
            value="x",
            changeset=changeset,
        )

    def instance(self, *, claim=None, source=None, locator=""):
        CitationInstance = self.apps.get_model("provenance", "CitationInstance")
        self._slug_seq += 1
        return CitationInstance.objects.create(
            citation_source=source or self.source,
            claim=claim,
            locator=locator,
            slug=_slug(self._slug_seq),
        )

    def link(self, claim, instance):
        ClaimCitationInstance = self.apps.get_model(
            "provenance", "ClaimCitationInstance"
        )
        return ClaimCitationInstance.objects.create(
            claim=claim, citation_instance=instance
        )

    def mark(self, instance):
        """Make *instance* a ``[[cite:...]]`` marker target (RecordReference)."""
        RecordReference = self.apps.get_model("core", "RecordReference")
        ci_ct = self.apps.get_model(
            "contenttypes", "ContentType"
        ).objects.get_or_create(app_label="provenance", model="citationinstance")[0]
        return RecordReference.objects.create(
            source_type=self.ct,
            source_id=999,
            target_type=ci_ct,
            target_id=instance.pk,
        )


def _forward(apps):
    _migration._forward(apps, None)


def _scalar_ids(apps):
    CitationInstance = apps.get_model("provenance", "CitationInstance")
    return set(
        CitationInstance.objects.filter(claim__isnull=False).values_list(
            "id", flat=True
        )
    )


def _links(apps, instance_id):
    ClaimCitationInstance = apps.get_model("provenance", "ClaimCitationInstance")
    return set(
        ClaimCitationInstance.objects.filter(
            citation_instance_id=instance_id
        ).values_list("claim_id", flat=True)
    )


@pytest.mark.django_db(transaction=True)
def test_backfill_synthesizes_self_link():
    with historical_apps(*_BEFORE) as apps:
        b = _Build(apps)
        claim = b.claim(b.changeset())
        inst = b.instance(claim=claim)

        _forward(apps)

        assert _links(apps, inst.id) == {claim.id}


@pytest.mark.django_db(transaction=True)
def test_collapse_merges_clones_and_repoints():
    with historical_apps(*_BEFORE) as apps:
        b = _Build(apps)
        cs = b.changeset()
        claim_a = b.claim(cs, key="year")
        claim_b = b.claim(cs, key="player_count")
        inst_a = b.instance(claim=claim_a)
        inst_b = b.instance(claim=claim_b)  # same source + locator + changeset

        _forward(apps)

        survivors = _scalar_ids(apps)
        assert survivors == {inst_a.id}  # min id wins
        assert _links(apps, inst_a.id) == {claim_a.id, claim_b.id}
        CitationInstance = apps.get_model("provenance", "CitationInstance")
        assert not CitationInstance.objects.filter(id=inst_b.id).exists()


@pytest.mark.django_db(transaction=True)
def test_distinct_locators_do_not_collapse():
    with historical_apps(*_BEFORE) as apps:
        b = _Build(apps)
        cs = b.changeset()
        inst_a = b.instance(claim=b.claim(cs, key="year"), locator="p. 1")
        inst_b = b.instance(claim=b.claim(cs, key="player_count"), locator="p. 2")

        _forward(apps)

        assert _scalar_ids(apps) == {inst_a.id, inst_b.id}


@pytest.mark.django_db(transaction=True)
def test_distinct_changesets_do_not_collapse():
    with historical_apps(*_BEFORE) as apps:
        b = _Build(apps)
        inst_a = b.instance(claim=b.claim(b.changeset()))
        inst_b = b.instance(claim=b.claim(b.changeset(), object_id=2))

        _forward(apps)

        assert _scalar_ids(apps) == {inst_a.id, inst_b.id}


@pytest.mark.django_db(transaction=True)
def test_inline_instances_untouched():
    with historical_apps(*_BEFORE) as apps:
        b = _Build(apps)
        cs = b.changeset()
        inst_a = b.instance(claim=b.claim(cs, key="year"))
        b.instance(claim=b.claim(cs, key="player_count"))  # its clone (the loser)
        inline = b.instance(claim=None)  # a footnote instance

        _forward(apps)

        CitationInstance = apps.get_model("provenance", "CitationInstance")
        assert CitationInstance.objects.filter(
            id=inline.id, claim__isnull=True
        ).exists()
        assert _links(apps, inline.id) == set()  # never joined
        assert _scalar_ids(apps) == {inst_a.id}  # the scalar pair still collapsed


@pytest.mark.django_db(transaction=True)
def test_marker_referenced_loser_becomes_survivor():
    with historical_apps(*_BEFORE) as apps:
        b = _Build(apps)
        cs = b.changeset()
        claim_a = b.claim(cs, key="year")
        claim_b = b.claim(cs, key="player_count")
        b.instance(claim=claim_a)  # lower id, would win by default
        inst_b = b.instance(claim=claim_b)
        b.mark(inst_b)  # a marker points at the higher-id clone

        _forward(apps)

        # The referenced clone is preserved so its slug/marker survives.
        assert _scalar_ids(apps) == {inst_b.id}
        assert _links(apps, inst_b.id) == {claim_a.id, claim_b.id}


@pytest.mark.django_db(transaction=True)
def test_multi_referenced_group_fails_fast():
    with historical_apps(*_BEFORE) as apps:
        b = _Build(apps)
        cs = b.changeset()
        inst_a = b.instance(claim=b.claim(cs, key="year"))
        inst_b = b.instance(claim=b.claim(cs, key="player_count"))
        b.mark(inst_a)
        b.mark(inst_b)

        with pytest.raises(RuntimeError, match="marker-referenced"):
            _migration._collapse_clones(apps)


@pytest.mark.django_db(transaction=True)
def test_duplicate_claim_in_group_fails_fast():
    with historical_apps(*_BEFORE) as apps:
        b = _Build(apps)
        cs = b.changeset()
        claim = b.claim(cs, key="year")
        # One claim owning two clones of the same evidence: the repoint would
        # collide, so the pre-scan must reject it by name.
        b.instance(claim=claim)
        b.instance(claim=claim)

        with pytest.raises(RuntimeError, match="prov_claimcite_unique"):
            _migration._collapse_clones(apps)


@pytest.mark.django_db(transaction=True)
def test_missing_loser_self_link_fails_fast():
    with historical_apps(*_BEFORE) as apps:
        b = _Build(apps)
        cs = b.changeset()
        claim_a = b.claim(cs, key="year")
        claim_b = b.claim(cs, key="player_count")
        inst_a = b.instance(claim=claim_a)
        b.instance(claim=claim_b)  # the loser -- deliberately left unlinked below
        # Only the survivor is linked; the loser has no join row, so the repoint
        # would move zero rows and drop claim_b's citation silently.
        b.link(claim_a, inst_a)

        with pytest.raises(RuntimeError, match="silently lose"):
            _migration._collapse_clones(apps)


@pytest.mark.django_db(transaction=True)
def test_assert_complete_catches_missing_self_link():
    # The primary backstop is exclude() + F() across a multi-valued reverse
    # relation -- prove it actually matches a non-self-linked instance.
    with historical_apps(*_BEFORE) as apps:
        b = _Build(apps)
        b.instance(claim=b.claim(b.changeset()))  # scalar, deliberately unlinked

        with pytest.raises(RuntimeError, match="missing its self-link"):
            _migration._assert_complete(apps)


@pytest.mark.django_db(transaction=True)
def test_assert_complete_allows_multi_claim_survivor():
    # The mirror of the above: a survivor legitimately carries links from several
    # claims and must NOT be flagged -- else every real migration run would fail.
    with historical_apps(*_BEFORE) as apps:
        b = _Build(apps)
        cs = b.changeset()
        claim_a = b.claim(cs, key="year")
        claim_b = b.claim(cs, key="player_count")
        inst = b.instance(claim=claim_a)
        b.link(claim_a, inst)  # its own self-link
        b.link(claim_b, inst)  # plus another claim's

        _migration._assert_complete(apps)  # does not raise


@pytest.mark.django_db(transaction=True)
def test_forward_is_idempotent():
    with historical_apps(*_BEFORE) as apps:
        b = _Build(apps)
        cs = b.changeset()
        b.instance(claim=b.claim(cs, key="year"))
        b.instance(claim=b.claim(cs, key="player_count"))

        _forward(apps)
        ClaimCitationInstance = apps.get_model("provenance", "ClaimCitationInstance")
        first_scalar = _scalar_ids(apps)
        first_links = set(
            ClaimCitationInstance.objects.values_list(
                "claim_id", "citation_instance_id"
            )
        )

        _forward(apps)  # re-run: no dup links, no extra deletes

        assert _scalar_ids(apps) == first_scalar
        assert set(
            ClaimCitationInstance.objects.values_list(
                "claim_id", "citation_instance_id"
            )
        ) == (first_links)
