import pytest
from constance.signals import config_updated
from django.core.cache import cache

from apps.catalog.cache import (
    _TITLES_FACETS_BASE,
    manufacturers_facets_key,
    titles_facets_key,
)
from apps.catalog.models import (
    Cabinet,
    CorporateEntity,
    CorporateEntityLocation,
    Credit,
    CreditRole,
    DisplaySubtype,
    DisplayType,
    Franchise,
    GameFormat,
    GameplayFeature,
    Location,
    MachineModel,
    Manufacturer,
    Person,
    RewardType,
    Series,
    System,
    Tag,
    TechnologyGeneration,
    TechnologySubgeneration,
    Theme,
    Title,
)
from apps.catalog.signals import _cache_invalidating_models


class TestModelSaveInvalidation:
    """A model ``.save()`` busts the cached facet payload through the ``post_save``
    signal. The facet-endpoint test files exercise hit/miss and call
    ``invalidate_all()`` directly; only this case proves the signal is actually
    wired and fires end-to-end (``TestCacheInvalidatingModelsParity`` checks the
    model *set*, not that a save triggers invalidation)."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        cache.clear()
        yield
        cache.clear()

    def test_title_save_invalidates_cache(self, client, db):
        title = Title.objects.create(
            name="Cactus Canyon", slug="cactus-canyon", opdb_id="CC1"
        )
        client.get("/api/pages/titles")
        assert cache.get(titles_facets_key()) is not None

        title.name = "Cactus Canyon Continued"
        title.save()
        assert cache.get(titles_facets_key()) is None


class TestCacheInvalidatingModelsParity:
    """Derived signal-connection set must match the expected model landscape.

    If this fails, a new ``CatalogModel`` was added (or an existing one removed)
    — update the expected set here intentionally rather than silently drifting.
    """

    def test_derived_set_matches_expected(self):
        expected = {
            Cabinet,
            CorporateEntity,
            CorporateEntityLocation,
            Credit,
            CreditRole,
            DisplaySubtype,
            DisplayType,
            Franchise,
            GameFormat,
            GameplayFeature,
            Location,
            MachineModel,
            Manufacturer,
            Person,
            RewardType,
            Series,
            System,
            Tag,
            TechnologyGeneration,
            TechnologySubgeneration,
            Theme,
            Title,
        }
        assert set(_cache_invalidating_models()) == expected


class TestPolicyChangeInvalidation:
    """Changing CONTENT_DISPLAY_POLICY busts cached facet payloads, since the
    rendered content depends on the active display threshold."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        cache.clear()
        yield
        cache.clear()

    def test_policy_change_invalidates_cache(self, client, machine_model):
        # Populate both audience slots — default via a vanilla request, kiosk
        # via a request carrying the mode=kiosk cookie. The policy-change
        # signal must clear both.
        client.get("/api/pages/titles")
        client.get("/api/pages/titles", HTTP_COOKIE="mode=kiosk")
        assert cache.get(f"{_TITLES_FACETS_BASE}:default") is not None
        assert cache.get(f"{_TITLES_FACETS_BASE}:kiosk") is not None

        config_updated.send(
            sender=None,
            key="CONTENT_DISPLAY_POLICY",
            old_value="licensed-only",
            new_value="show-all",
        )
        assert cache.get(f"{_TITLES_FACETS_BASE}:default") is None
        assert cache.get(f"{_TITLES_FACETS_BASE}:kiosk") is None

    def test_unrelated_key_change_does_not_invalidate(self, client, machine_model):
        client.get("/api/pages/titles")
        assert cache.get(titles_facets_key()) is not None

        config_updated.send(
            sender=None,
            key="SOME_OTHER_KEY",
            old_value="a",
            new_value="b",
        )
        assert cache.get(titles_facets_key()) is not None


class TestKioskAudienceCacheIsolation:
    """Kiosk and default audiences must populate separate cache slots.

    The middleware reads ``mode=kiosk`` from request cookies and flips a
    contextvar that ``current_audience()`` reads, which is what
    ``titles_facets_key()`` / ``manufacturers_facets_key()`` / etc. fold into
    the cache key.
    """

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        cache.clear()
        yield
        cache.clear()

    def test_kiosk_request_populates_kiosk_slot_only(self, client, machine_model):
        client.get("/api/pages/titles", HTTP_COOKIE="mode=kiosk")
        assert cache.get(f"{_TITLES_FACETS_BASE}:kiosk") is not None
        assert cache.get(f"{_TITLES_FACETS_BASE}:default") is None

    def test_default_request_populates_default_slot_only(self, client, machine_model):
        client.get("/api/pages/titles")
        assert cache.get(f"{_TITLES_FACETS_BASE}:default") is not None
        assert cache.get(f"{_TITLES_FACETS_BASE}:kiosk") is None

    def test_kiosk_payload_not_served_to_default_request(self, client, machine_model):
        # Warm only the kiosk slot.
        client.get("/api/pages/titles", HTTP_COOKIE="mode=kiosk")
        assert cache.get(f"{_TITLES_FACETS_BASE}:kiosk") is not None
        assert cache.get(f"{_TITLES_FACETS_BASE}:default") is None

        # A subsequent default-audience request must not reuse the kiosk
        # slot — it populates its own slot fresh.
        resp = client.get("/api/pages/titles")
        assert resp.status_code == 200
        assert cache.get(f"{_TITLES_FACETS_BASE}:default") is not None


class TestConditionalGet:
    """Pre-computed ETags let ConditionalGetMiddleware return 304 without
    serialising or hashing the response body."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        cache.clear()
        yield
        cache.clear()

    @pytest.mark.parametrize("path", ["/api/pages/titles", "/api/pages/manufacturers"])
    def test_304_on_matching_etag(self, client, machine_model, path):
        resp = client.get(path)
        assert resp.status_code == 200
        etag = resp["ETag"]
        assert etag

        resp2 = client.get(path, headers={"If-None-Match": etag})
        assert resp2.status_code == 304

    @pytest.mark.parametrize("path", ["/api/pages/titles", "/api/pages/manufacturers"])
    def test_200_on_stale_etag(self, client, machine_model, path):
        client.get(path)  # populate cache

        resp = client.get(path, headers={"If-None-Match": '"stale"'})
        assert resp.status_code == 200
        assert resp["ETag"]

    @pytest.mark.parametrize(
        ("path", "cache_key"),
        [
            ("/api/pages/titles", titles_facets_key()),
            ("/api/pages/manufacturers", manufacturers_facets_key()),
        ],
    )
    def test_cache_stores_bytes_and_etag(self, client, machine_model, path, cache_key):
        client.get(path)
        cached = cache.get(cache_key)
        assert cached is not None
        json_bytes, etag = cached
        assert isinstance(json_bytes, bytes)
        assert etag.startswith('"')
        assert etag.endswith('"')


class TestSetCachedResponseValidation:
    """Lock down the DEBUG-mode shape check in :func:`set_cached_response`.

    The prod path is raw ``json.dumps`` for speed, so the validation step is
    the only place that catches dict/Schema drift. Tests run with DEBUG=True
    by default; if that ever changes, this guard goes silent.
    """

    def test_debug_mode_rejects_data_not_matching_adapter(self, db, settings):
        from pydantic import TypeAdapter, ValidationError

        from apps.catalog.cache import set_cached_response

        settings.DEBUG = True
        adapter: TypeAdapter[list[dict[str, int]]] = TypeAdapter(list[dict[str, int]])
        with pytest.raises(ValidationError):
            set_cached_response("test:bogus", adapter, [{"x": "not-an-int"}])

    def test_prod_mode_skips_validation(self, db, settings):
        """In prod, malformed-but-JSON-serializable data is cached as-is —
        the trade-off documented in :func:`set_cached_response`."""
        from pydantic import TypeAdapter

        from apps.catalog.cache import set_cached_response

        settings.DEBUG = False
        adapter: TypeAdapter[list[dict[str, int]]] = TypeAdapter(list[dict[str, int]])
        resp = set_cached_response("test:bogus", adapter, [{"x": "not-an-int"}])
        assert resp.status_code == 200
        assert b'"x":"not-an-int"' in resp.content
