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
from apps.citation.models import CitationSource
from apps.provenance.models import Claim, Source


def make_machine_model(
    *, title=None, name="Test Machine", slug=None, **kwargs
) -> MachineModel:
    """Create a MachineModel for tests, auto-providing a Title when omitted.

    MachineModel.title is NOT NULL; tests that don't care about the title
    value get a disposable one derived from the machine's slug/name.

    A bootstrap name claim is asserted on the MachineModel and on any
    auto-created Title so ``resolve_machine_models()`` doesn't reset
    those names to blank. Callers that supply their own ``title=`` are
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
            Claim.objects.assert_claim(title, "name", name, source=src)
    mm = MachineModel.objects.create(
        title=title,
        name=name,
        slug=resolved_slug,
        **kwargs,
    )
    Claim.objects.assert_claim(mm, "name", name, source=src)
    return mm


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
def _bootstrap_source(db):
    """Low-priority source for seeding name claims in shared fixtures.

    Priority 1 ensures bootstrap claims never outrank real source or user
    claims in tests that set up competing claims.
    """
    return Source.objects.create(
        name="Bootstrap", slug="bootstrap", source_type="editorial", priority=1
    )


@pytest.fixture
def source(db):
    return Source.objects.create(name="IPDB", source_type="database", priority=10)


@pytest.fixture
def ipdb_root(db):
    """The root CitationSource for the ipdb scheme (children hang under it)."""
    return CitationSource.objects.create(
        name="Internet Pinball Database",
        source_type="web",
        identifier_key="ipdb",
    )


@pytest.fixture
def kineticist_root(db):
    """A non-scheme root web source with a homepage link, for domain matching."""
    root = CitationSource.objects.create(name="Kineticist", source_type="web")
    root.links.create(link_type="homepage", url="https://kineticist.com/")
    root.root_domains.create(host="kineticist.com")  # the recognition signal
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
def manufacturer(db, _bootstrap_source):
    mfr = Manufacturer.objects.create(name="Williams", slug="williams")
    Claim.objects.assert_claim(mfr, "name", "Williams", source=_bootstrap_source)
    return mfr


@pytest.fixture
def stern(db, _bootstrap_source):
    mfr = Manufacturer.objects.create(name="Stern", slug="stern")
    Claim.objects.assert_claim(mfr, "name", "Stern", source=_bootstrap_source)
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
def person(db, _bootstrap_source):
    p = Person.objects.create(name="Pat Lawlor", slug="pat-lawlor")
    Claim.objects.assert_claim(p, "name", "Pat Lawlor", source=_bootstrap_source)
    return p


@pytest.fixture
def solid_state(db):
    return TechnologyGeneration.objects.create(name="Solid State", slug="solid-state")


@pytest.fixture
def williams_entity(db, manufacturer, _bootstrap_source):
    ce = CorporateEntity.objects.create(
        name="Williams Electronics",
        slug="williams-electronics",
        manufacturer=manufacturer,
    )
    Claim.objects.assert_claim(
        ce, "name", "Williams Electronics", source=_bootstrap_source
    )
    return ce


@pytest.fixture
def stern_entity(db, stern, _bootstrap_source):
    ce = CorporateEntity.objects.create(
        name="Stern Pinball, Inc.",
        slug="stern-pinball-inc",
        manufacturer=stern,
    )
    Claim.objects.assert_claim(
        ce, "name", "Stern Pinball, Inc.", source=_bootstrap_source
    )
    return ce


@pytest.fixture
def machine_model(db, williams_entity, solid_state, _bootstrap_source):
    title = Title.objects.create(name="Medieval Madness", slug="medieval-madness-title")
    Claim.objects.assert_claim(
        title, "name", "Medieval Madness", source=_bootstrap_source
    )
    pm = MachineModel.objects.create(
        name="Medieval Madness",
        slug="medieval-madness",
        title=title,
        corporate_entity=williams_entity,
        year=1997,
        technology_generation=solid_state,
    )
    Claim.objects.assert_claim(pm, "name", "Medieval Madness", source=_bootstrap_source)
    t = Theme.objects.create(name="Medieval", slug="medieval")
    pm.themes.add(t)
    return pm


@pytest.fixture
def another_model(db, stern_entity, solid_state, _bootstrap_source):
    title = Title.objects.create(name="The Mandalorian", slug="the-mandalorian-title")
    Claim.objects.assert_claim(
        title, "name", "The Mandalorian", source=_bootstrap_source
    )
    pm = MachineModel.objects.create(
        name="The Mandalorian",
        slug="the-mandalorian",
        title=title,
        corporate_entity=stern_entity,
        year=2021,
        technology_generation=solid_state,
    )
    Claim.objects.assert_claim(pm, "name", "The Mandalorian", source=_bootstrap_source)
    return pm
