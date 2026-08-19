import pytest
from django.test import Client
from django.utils.text import slugify

from apps.catalog.models import (
    CorporateEntity,
    CreditRole,
    MachineModel,
    Manufacturer,
    Person,
    TechnologyGeneration,
    Theme,
    Title,
)
from apps.citation.test_factories import (
    make_citation_link,
    make_citation_root_domain,
    make_citation_source,
)
from apps.provenance.models import ClaimControlledModel, Source
from apps.provenance.test_factories import make_claim, make_ingest_source


def make_machine_model(
    *,
    title: Title | None = None,
    name: str = "Test Machine",
    slug: str | None = None,
    **kwargs,
) -> MachineModel:
    """Create a MachineModel for tests, auto-providing a Title when omitted.

    MachineModel.title is NOT NULL; tests that don't care about the title
    value get a disposable one derived from the machine's slug/name.

    A bootstrap name claim is asserted on the MachineModel and on any
    auto-created Title so resolution doesn't reset those names to blank.
    Callers that supply their own ``title=`` are
    responsible for backing it with their own name claim before running
    the resolver — otherwise the resolver will wipe ``title.name`` to
    ``""`` and trip the Title CHECK constraint.
    """
    resolved_slug = slug or slugify(name)
    src, _ = Source.objects.get_or_create(
        slug="bootstrap",
        defaults={
            "name": "Bootstrap",
            "source_type": "editorial",
            "priority": 1,
        },
    )
    if title is None:
        t_slug = f"auto-title-{resolved_slug}"
        title, created = Title.objects.get_or_create(
            slug=t_slug, defaults={"name": name}
        )
        if created:
            make_claim(title, "name", name, ingest_source=src)
    mm = MachineModel.objects.create(
        title=title,
        name=name,
        slug=resolved_slug,
        **kwargs,
    )
    make_claim(mm, "name", name, ingest_source=src)
    return mm


def bulk_resolve(
    model_class: type[ClaimControlledModel] = MachineModel,
    subject_ids: set[int] | None = None,
) -> int:
    """Resolve a model's rows through the generic bulk dispatch (test helper).

    Re-resolves scalars/FKs plus every relationship namespace for which the
    model is a valid subject (including ``media_attachment``). Resolves all rows
    of *model_class* unless *subject_ids* is given. Returns the number of
    subjects resolved.

    Does NOT run a cross-entity dependency preamble (locations/taxonomy/titles
    before dependents) — FK targets must already exist as rows, which they do in
    tests (FK lookup is by slug).
    """
    from apps.provenance.resolution import resolve_entities_bulk
    from apps.provenance.validation import (
        get_relationship_namespaces,
        get_relationship_schema,
    )

    if subject_ids is None:
        subject_ids = set(
            model_class.objects.values_list("pk", flat=True)  # type: ignore[attr-defined]
        )
    if not subject_ids:
        return 0
    namespaces = {
        ns
        for ns in get_relationship_namespaces()
        if (schema := get_relationship_schema(ns)) is not None
        and model_class in schema.valid_subjects
    }
    resolve_entities_bulk(model_class, subject_ids, namespaces)
    return len(subject_ids)


SAMPLE_IMAGES = [
    {
        "primary": True,
        "type": "backglass",
        "urls": {
            "small": "https://img.opdb.org/sm.jpg",
            "medium": "https://img.opdb.org/md.jpg",
            "large": "https://img.opdb.org/lg.jpg",
        },
    }
]


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def source(db):
    return make_ingest_source(name="IPDB", source_type="database", priority=10)


@pytest.fixture
def ipdb_root(db):
    """The root CitationSource for the ipdb scheme (children hang under it)."""
    return make_citation_source(
        name="Internet Pinball Database",
        source_type="web",
        identifier_key="ipdb",
    )


@pytest.fixture
def kineticist_root(db):
    """A non-scheme root web source with a homepage link, for domain matching."""
    root = make_citation_source(name="Kineticist", source_type="web")
    make_citation_link(
        citation_source=root, link_type="homepage", url="https://kineticist.com/"
    )
    make_citation_root_domain(source=root, host="kineticist.com")  # recognition signal
    return root


@pytest.fixture
def flipcommons_catalog(db):
    """The default patch-attribution Source.

    No migration creates ``flipcommons-catalog``; it lives in the database
    baseline (loaded via DB export/import), so a fresh test database lacks it.
    Tests that attribute patches to the catalog's own default source must
    therefore seed it themselves. It's the
    default attribution for hand- and AI-authored patches — see
    docs/DataPatchAuthoring.md.
    """
    src, _ = Source.objects.get_or_create(
        slug="flipcommons-catalog",
        defaults={
            "name": "Flipcommons Catalog",
            "source_type": "editorial",
            "priority": 300,
        },
    )
    return src


@pytest.fixture
def manufacturer(db, bootstrap_source):
    mfr = Manufacturer.objects.create(name="Williams", slug="williams")
    make_claim(mfr, "name", "Williams", ingest_source=bootstrap_source)
    return mfr


@pytest.fixture
def stern(db, bootstrap_source):
    mfr = Manufacturer.objects.create(name="Stern", slug="stern")
    make_claim(mfr, "name", "Stern", ingest_source=bootstrap_source)
    return mfr


_CREDIT_ROLES = [
    {"slug": "animation", "name": "Dots/Animation", "display_order": 40},
    {"slug": "art", "name": "Art", "display_order": 30},
    {"slug": "concept", "name": "Concept", "display_order": 20},
    {"slug": "design", "name": "Design", "display_order": 10},
    {"slug": "mechanics", "name": "Mechanics", "display_order": 50},
    {"slug": "music", "name": "Music", "display_order": 60},
    {"slug": "other", "name": "Other", "display_order": 100},
    {"slug": "software", "name": "Software", "display_order": 90},
    {"slug": "sound", "name": "Sound", "display_order": 70},
    {"slug": "voice", "name": "Voice", "display_order": 80},
]


@pytest.fixture
def credit_roles(db):
    """Seed all credit roles for tests that need them."""
    return CreditRole.objects.bulk_create(
        [CreditRole(**entry) for entry in _CREDIT_ROLES],
        update_conflicts=True,
        unique_fields=["slug"],
        update_fields=["name", "display_order"],
    )


@pytest.fixture
def person(db, bootstrap_source):
    p = Person.objects.create(name="Pat Lawlor", slug="pat-lawlor")
    make_claim(p, "name", "Pat Lawlor", ingest_source=bootstrap_source)
    return p


@pytest.fixture
def solid_state(db):
    return TechnologyGeneration.objects.create(name="Solid State", slug="solid-state")


@pytest.fixture
def williams_entity(db, manufacturer, bootstrap_source):
    ce = CorporateEntity.objects.create(
        name="Williams Electronics",
        slug="williams-electronics",
        manufacturer=manufacturer,
    )
    make_claim(ce, "name", "Williams Electronics", ingest_source=bootstrap_source)
    return ce


@pytest.fixture
def stern_entity(db, stern, bootstrap_source):
    ce = CorporateEntity.objects.create(
        name="Stern Pinball, Inc.",
        slug="stern-pinball-inc",
        manufacturer=stern,
    )
    make_claim(ce, "name", "Stern Pinball, Inc.", ingest_source=bootstrap_source)
    return ce


@pytest.fixture
def machine_model(db, williams_entity, solid_state, bootstrap_source):
    title = Title.objects.create(name="Medieval Madness", slug="medieval-madness-title")
    make_claim(title, "name", "Medieval Madness", ingest_source=bootstrap_source)
    pm = MachineModel.objects.create(
        name="Medieval Madness",
        slug="medieval-madness",
        title=title,
        corporate_entity=williams_entity,
        production_year=1997,
        technology_generation=solid_state,
    )
    make_claim(pm, "name", "Medieval Madness", ingest_source=bootstrap_source)
    t = Theme.objects.create(name="Medieval", slug="medieval")
    pm.themes.add(t)
    return pm


@pytest.fixture
def another_model(db, stern_entity, solid_state, bootstrap_source):
    title = Title.objects.create(name="The Mandalorian", slug="the-mandalorian-title")
    make_claim(title, "name", "The Mandalorian", ingest_source=bootstrap_source)
    pm = MachineModel.objects.create(
        name="The Mandalorian",
        slug="the-mandalorian",
        title=title,
        corporate_entity=stern_entity,
        production_year=2021,
        technology_generation=solid_state,
    )
    make_claim(pm, "name", "The Mandalorian", ingest_source=bootstrap_source)
    return pm
