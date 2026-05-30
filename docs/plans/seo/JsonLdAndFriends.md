# Generating Structured Data For Search Engines, Social and LLMs

## Goal

Every public page should emit machine-readable representations of itself for external consumers:

- JSON-LD/schema.org for search engines
- OpenGraph and Twitter Cards for social platforms and chat clients
- the `<head>` pipeline via title/description/canonical
- the sitemap with image extensions for Google Image Search

This is not just SEO. A catalog/encyclopedia site that emits consistent, addressable, machine-readable entity representations becomes a reference source on the open web — LLM crawlers cite it more accurately, other databases can link in, link previews on Discord and Reddit read as archival and authoritative.

## Types of metadata

### Traditional head info

The original SEO primitives: `<title>`, `<meta name="description">` and `<link rel="canonical">`. These are still consumed by every search engine, browser tab, bookmark system and accessibility tool. Lowest fidelity but most universal.

Each layout hand-picks the relevant fields (title, description, hero image, alt text) and passes them in:

- Listing pages emit `<title>` only (no description, no canonical) because they're CSR for now.
- Detail pages emit all three.
  - Taxonomy, Series and Franchise detail layouts source their meta/OG descriptions from `RichTextSchema.plain` via `metaDescriptionFor(profile)`, so markdown syntax and `[[type:slug]]` reference tokens do not leak into machine-readable descriptions.

### Open Graph

Open Graph (OG) is the de facto link-preview standard: Facebook, LinkedIn, iMessage, Slack, Discord, Bluesky, Mastodon (and Twitter as a fallback) all read OG. These are `<meta property="og:*">` tags.

We emit the full set of OG tags: `og:site_name`, `og:type`, `og:title`, `og:description`, `og:url`, `og:image` and `og:image:alt`. Pages with no entity image fall back to a single site-wide branded default (`static/images/social_default.png`, 1200×630) emitted with `og:image:width`/`og:image:height`/`og:image:type` so Facebook/LinkedIn render the card on first scrape. The fallback is wired once in `MetaTags.svelte`, so every call site gets it for free; `static/` assets are absolutized via `absoluteAssetUrl`.

Each layout hand-picks the relevant fields:

- `og:type`: Person layouts emit `profile`, static pages emit `website`, default is `article`. User pages are CSR-only today and still use a hand-written `<title>` rather than `MetaTags`; see [CSR pages: out of scope](#csr-pages-out-of-scope).
- `og:image:alt` is phrased to match what the image actually is: Model/Title emit `` `${name} pinball machine` ``, Person `` `Photo of ${name}` ``, Manufacturer `` `${name} logo` ``. CorporateEntity, System and other imageless pages fall through to the branded default image and its generic alt.

**Gaps**:

- Listing pages. They're currently CSR and therefore emit nothing (see [CSR pages: out of scope](#csr-pages-out-of-scope)).

### Twitter card

Twitter uses `<meta name="twitter:*">` tags to control previews on its site. Twitter cascades from Open Graph when Twitter-specific tags are absent, so they aren't strictly needed to render — but SEO/preview validators do a literal presence check and dock the missing ones, so we emit the explicit set anyway: `twitter:card`, `twitter:title`, `twitter:description`, `twitter:image` and `twitter:image:alt`. `twitter:title`/`twitter:description` mirror their OG counterparts; `twitter:image` is the entity image when present, else the same 1200×630 default as `og:image`, with alt to match.

✅ DONE — `twitter:card` is always `summary_large_image`. We deliberately do **not** use the small `summary` card: in practice almost every previewer (Slack, Discord, iMessage, LinkedIn, Facebook, Bluesky and X's own large card) renders `og:image` and ignores Twitter's small-card mode, so a single landscape asset previews cleanly everywhere. An earlier attempt at a dedicated square `summary` thumbnail was dropped — the one surface that still honored it cropped the square badly, and maintaining a second asset bought nothing. One default (`DEFAULT_SOCIAL_IMAGE` in `meta-tags.ts`, asset `static/images/social_default.png`) now feeds both `og:image` and `twitter:image`.

**Gap**: `twitter:site`/`twitter:creator` need an X/@handle the project doesn't have yet. Add a site-wide constant and emit `twitter:site` once one exists; some validators flag its absence.

### JSON-LD

A JSON document inside `<script type="application/ld+json">` in `<head>`, using vocabularies from [schema.org](https://schema.org). Consumed by search engines for rich results and knowledge panels, by LLM crawlers for citation accuracy and by other databases linking in via `sameAs`. Each page emits a `@graph` of one or more typed nodes (`Game`, `Person`, `Organization`, etc.) with `@id` cross-references to related entities and `sameAs` to external IDs. The highest-fidelity representation — arbitrarily rich, nested and addressable.

As a public data project, JSON-LD should be a key part of our public data strategy. We want to emit consistent, addressable, machine-readable JSON-LD to become a reference source on the open web — LLM crawlers cite it more accurately, other databases can link in, link previews on Discord and Reddit read as archival and authoritative.

What currently emits JSON-LD:

- Every catalog detail page
- Every static page (About, Privacy etc)

**Gaps**:

- Person date precision is year-only. We collect month and day and should emit them.
- `User` detail does not emit JSON-LD (it's CSR not SSR right now).
- Some MachineModel FK mappings — system, technology_generation, display_type, cabinet — have no clean schema.org property yet and thus are not emitted in JSON-LD.
- Entity meta-pages — edit history, sources — do not emit JSON-LD.

### Sitemap

`/sitemap.xml` tells search engines which pages exist, when they last changed, and — via the image extension — which images belong to each page.

This project already has a standard sitemap (URLs + `<lastmod>`), but it does not have the **image extension**. This is an `<image:image>` per URL, declaring associated images with title and caption. The sitemap image extension is new and the highest-leverage Google Image Search hook for a visual encyclopedia.

This project currently uses `super-sitemap` to generate the sitemap, which doesn't support the image extension. TBD how we'll support the image extension.

## Schema.org types

| Django Model            | Example       | schema.org types   |
| ----------------------- | ------------- | ------------------ |
| Title                   | Godzilla      | Game               |
| MachineModel            | Godzilla Pro  | Game, ProductModel |
| Manufacturer            | Atari         | Brand              |
| CorporateEntity         | Atari, Inc    | Organization       |
| Person                  | Pat Lawlor    | Person             |
| User                    | moses         | Person             |
| Location                | Chicago       | Place†             |
| Series                  | Eight Ball    | CreativeWorkSeries |
| Franchise               | Jurassic Park | CreativeWork       |
| System                  | Stern SPIKE 2 | CreativeWork       |
| Theme                   | Fantasy       | DefinedTerm        |
| GameplayFeature         | Multiball     | DefinedTerm        |
| TechnologyGeneration    | Solid State   | DefinedTerm        |
| TechnologySubgeneration | PC-Based      | DefinedTerm        |
| DisplayType             | Alphanumeric  | DefinedTerm        |
| DisplaySubtype          | Nixie Tube    | DefinedTerm        |
| Cabinet                 | Cocktail      | DefinedTerm        |
| GameFormat              | Pinball       | DefinedTerm        |
| RewardType              | Replay        | DefinedTerm        |
| Tag                     | Prototype     | DefinedTerm        |
| CreditRole              | Design        | Occupation         |

† Each individual Location record will be a specific type of Place: AdministrativeArea, Country, State, or City. See the Location example in [Per-model frontend info](#per-model-frontend-info).

## Open Graph page types

| Page                                                            | `og:type` |
| --------------------------------------------------------------- | --------- |
| Home (`/`) and legal pages (`/privacy`, `/terms`, `/licensing`) | `website` |
| Person detail pages                                             | `profile` |
| User detail pages, once SSR + `MetaTags` land                   | `profile` |
| Everything else                                                 | `article` |

"Everything else" includes all other catalog entity detail pages (Title, MachineModel, Manufacturer, CorporateEntity, Location, Series, Franchise, System, Theme, all taxonomy classes), all entity meta-pages (`/edit-history`, `/sources`), and the prose static pages (`/about`, `/about/people`).

Legal pages get `website` rather than `article` because they aren't articles in OG's editorial sense — no author, no published date, no section. `website` is the honest "we don't have a better type for this." `/about` and `/about/people` stay `article` because they're editorial-style prose describing the project and team.

`article` isn't a perfect semantic match for any of those (a Manufacturer isn't an article, a taxonomy term isn't an article), but it's the closest of OG's available choices and it's at least less wrong than calling everything a `website`. The Person → profile case is the one genuine fit and the one place dynamic typing pays off — Facebook and LinkedIn render profile-card previews differently from article previews, so designer/artist pages get a small but visible improvement when shared on social.

We don't use `product` (Facebook's extension) for MachineModel — it's commerce-oriented (price, availability, SKU) and we're not selling machines.

The og:type mapping is a single central rule keyed off the page, not a per-entity declaration in the per-model TS files — don't look for an `ogType` there.

## Architecture

### Autogenerated representations

We will automatically generate these different machine-readable representations based on information in the Django models, as per [ModelDrivenMetadata.md](docs/plans/model_driven_metadata/ModelDrivenMetadata.md).

The same facts feed all of these machine-readable representations. 90% of this information is already well-described by the model and won't require additional per-model mapping information.

#### Information sources

Some come from the Django model (backend), some from the per-model TS file ([see below](#per-model-frontend-info)):

- **Canonical URL** — `LinkableModel.get_absolute_url()` (backend; already in API responses)
- **Display name** — `LinkableModel.name` (backend)
- **Description** — `RichTextSchema.plain`, a backend-flattened prose projection of the entity's markdown description. Frontend display consumers truncate it per surface: `<meta name="description">` ~155 chars (Google SERP display limit), `og:description` ~200 chars (Facebook/LinkedIn preview cards), `twitter:description` ~200 chars (when emitted; usually cascades from OG). JSON-LD `description` is **not truncated** — machine-readable consumers (LLMs, search engines, linked-data crawlers) benefit from the full text and have no display constraint.
- **Image URL** — current detail schemas expose image fields per entity (`hero_image_url` for Title/Model, `logo_url` for Manufacturer, `photo_url` for Person). These are constructed absolute URL strings from the media pipeline and are already suitable for OG / JSON-LD consumers. A future [`MediaSupportedModel.primary_image`](#mediasupportedmodel) helper could consolidate image selection for entities with own media, but it is not implemented yet; Title's image still comes from its child-Model aggregation, and CorporateEntity currently omits an image.

  **Deliberate exception to "presentation lives frontend-side":** the choice of which rendition to emit (`display` vs `thumb` vs `original`) is a presentation decision, but it's encoded in the Python `build_public_url(... "display")` call rather than in TS. The CDN base URL (`MEDIA_PUBLIC_BASE_URL`) is server-side config that isn't (and shouldn't be) exposed to the frontend, so URL construction has to happen backend. We could ship the asset's UUID + rendition_type and have TS build the URL — but that means duplicating the base URL into frontend env, and the storage layer's URL conventions naturally belong with the storage layer. Net: one small backend presentational decision (rendition selection), justified by where the URL construction primitive lives.

  **Frontend static assets** (`/og-default.png`, future auto-composited share images stored under `static/`) are a separate path — absolutize via `lib/utils.absoluteAssetUrl(path, pageUrl)`, which routes through SvelteKit's `asset()` and the URL constructor so a configured CDN base or empty-base local dev both work. Backend-served images already arrive absolute and skip this helper.

- **Last modified** — the same value the sitemap emits as `<lastmod>`: the freshness concept lives on `LastUpdatedModel` as `lastmod_expression()` (the queryset expression both the sitemap and the detail-page annotation consume) and `last_modified` (the per-instance value, read off the `_last_modified` annotation), **not** raw `updated_at`. The default expression is `F("updated_at")`, but overrides widen it — `Title` overrides `lastmod_expression()` to `Greatest(updated_at, Max(machine_models__updated_at))` so a Title's freshness reflects edits to its child Models. JSON-LD `dateModified` and sitemap `<lastmod>` both annotate via that one expression so they can't disagree; the detail response carries it as `LastModifiedDetailSchema.last_modified` and the central `register_entity_detail_page` annotates every detail queryset with `model_cls.lastmod_expression()`.
- **Schema.org types** — declared in the per-model TS file's `schemaOrg.types` field. Static array for most entities; per-row function for Location. See [Per-model frontend info](#per-model-frontend-info).
- **Cross-references** — declared in the per-model TS file's `schemaOrg.relationshipMap`. Each declared FK / M2M attribute carries **only** its schema.org property name (`corporate_entity → brand`, `title → exampleOfWork`, `themes → genre`, etc.) — that name is presentation vocabulary Django can't express. The referent's canonical URL is _not_ declared here; it's constructed from the codegen'd relationship shape (see [Related-entity URLs](#related-entity-urls-from-entity-metats)). The frontend metadata builder walks the declared set and emits an `@id` reference to the referent's canonical URL under the declared property. Undeclared relationships are not emitted.
- **External-system identity** — ✅ DONE via the per-entity `externalRefs` registry (`frontend/src/lib/entities/<model>.ts`), keyed by field name (`wikidata_id`, `opdb_id`, `ipdb_id`, `opdb_manufacturer_id`, `ipdb_manufacturer_id`, `pinside_id`, `fandom_page_id`). Field-name-based, not prefix-based — `ipdb_rating` is a number, not an ID, and won't accidentally match. Each present, non-null field with a `urlTemplate` becomes a `sameAs`; one with only an `identifier` becomes a schema.org `PropertyValue`. The same registry drives the visible "External Links" UI, so links and structured-data identities can't drift. See [External references](#external-references--sameas--identifier).

### Backend vs frontend responsibilities

All metadata assembly — JSON-LD, head, OG, Twitter — lives in the frontend. Backend ships raw entity facts; the frontend reads them plus per-model declarations from [`frontend/src/lib/entities/`](#per-model-frontend-info) and emits the metadata.

#### Backend's job

Serve raw entity facts on the entity detail API response: `name`, `description` (`RichTextSchema`, including backend-rendered `.plain`), any per-entity image URL field (`hero_image_url`, `logo_url`, `photo_url`, etc.), FK / M2M references as public-id-bearing refs (`{name, public_id}` — no `href`; the frontend constructs canonical URLs, see [Related-entity URLs](#related-entity-urls-from-entity-metats)), and external-ID scalars where a schema already exposes them (`ipdb_id`, `opdb_id`, etc.). `updated_at`, `wikidata_id`, and a normalized image field are not universal detail-schema facts yet; see [API response audit](#api-response-audit) below.

#### Frontend's job

- **Hold per-model presentation declarations** in [`frontend/src/lib/entities/<model-name>.ts`](#per-model-frontend-info) — one file per Django model, containing the schema.org types, field map, relationship map, and any other purely-presentation per-model info. ✅ DONE for the taxonomy tranche's 11 entities, plus `manufacturer.ts` and `system.ts`.
- **Assemble the SchemaOrgNode** for each entity via a generic `buildSchemaOrgNode(entity, modelInfo)` function that walks the declarations against the entity facts.
  - ✅ DONE for `@type`, `@id`, `name` and untruncated `description.plain`;
  - ✅ DONE for the `fieldMap` walk (scalar field → schema.org property, skipping null/empty — e.g. `logo_url → logo`), its `{ property, transform: 'year' }` value-transform form (int year → partial-ISO string — see [Value transformations](#value-transformations)) and the `relationshipMap` walk (cross-reference `@id`s: a single object for an FK, an array for a `many: true` M2M, dropped when empty);
  - ✅ DONE for the `externalRefs` walk (`sameAs` array + `identifier` `PropertyValue`s — see [External references](#external-references--sameas--identifier));
  - TODO to widen for images sourced from `primary_image` (today an image rides `fieldMap` under its per-entity field name, e.g. `logo_url`).
- **Compose the `@graph`** per page — pick which nodes go in (entity node always; Model node for single-Model Titles when `data.model_detail` is present; `BreadcrumbList`; `CollectionPage` for meta-pages).
- **Apply route-specific page typing** — entity detail pages emit the entity node; meta-pages emit `CollectionPage` with `about` → entity; static pages emit `AboutPage` / `WebPage`.
- **Assemble head / OG / Twitter tags** (already happens today in [`MetaTags.svelte`](frontend/src/lib/components/MetaTags.svelte) and [`./meta-tags.ts`](frontend/src/lib/components/meta-tags.ts)). Truncation, site-name suffix, canonical URL absolutization, OG-type bucket, Twitter-card decision — all presentation transforms with knowledge that lives frontend-side.
- **Maintain the `externalRefs` registry** — ✅ DONE. Each entity's per-model TS file declares `externalRefs` (keyed by field name, values typed `ExternalReference`). It's the single source of truth for both the JSON-LD `sameAs`/`identifier` and the visible "External Links" UI. See [External references](#external-references--sameas--identifier).

**Two cross-cutting disciplines** apply to every JSON-LD emission, including the model-driven entity-page assembler:

- **`paths.base` discipline.** Every internal URL emitted into JSON-LD — entity `@id`s derived from `get_absolute_url()`, cross-reference `@id`s constructed from a referent's `public_id` + relationship shape, `BreadcrumbList` items, `isPartOf` references — must be routed through `resolveHref()` before being concatenated with the origin, so a future `config.kit.paths.base` setting doesn't desynchronize JSON-LD URLs from rendered `<a>` hrefs. Reuse the `absolutize(pageUrl, path)` helper in [`jsonld.ts`](frontend/src/lib/components/jsonld.ts) — it already does this. Note that `pageUrl.pathname` already contains the base prefix, so callers using the current page's pathname should NOT route it back through `absolutize()`.
- **HTML-safe serialization.** All JSON-LD must be emitted through the [`JsonLd.svelte`](frontend/src/lib/components/JsonLd.svelte) component, which escapes `<`, `>`, `&` to `\uXXXX` so user-controlled content (entity descriptions, names) can't break out of the `<script>` tag. Never inline a raw `<script type="application/ld+json">` tag in a route — it bypasses the escape and exposes a content-injection hole. (Aside: Svelte treats literal `<script>` element children as opaque text and skips `{@html}` interpolation inside them, so the component emits the whole tag-payload-tag string via `{@html}` instead.)

#### Why frontend assembly

The declarations are presentation-only: schema.org type names, schema.org property names, OG type buckets — backend never uses them. Knowledge belongs where the consumer is. An alternative would be to declare them in Python and codegen to TS (parallel to `schema.d.ts`), but a hand-edited per-model TS file type-checked against `schema.d.ts` catches drift just as well without the codegen pipeline.

This applies to the _presentation vocabulary_ only. The _structural shape_ of the catalog — which fields are relations, what they target, FK vs M2M — is not presentation; it's a fact Django already owns and can derive from `_meta`. Per the model-driven principle ("derive from `_meta` whenever possible; declare only what Django can't express", [ModelDrivenMetadata.md](../model_driven_metadata/ModelDrivenMetadata.md)), that part _is_ codegen'd — see below.

#### Related-entity URLs from `entity-meta.ts`

A cross-reference emits `{"@id": "<canonical URL of the referent>"}`. The referent ships as an `EntityRef` or equivalent nested referent shape (`{name, public_id}` plus any display extras), no `href` and no type tag. A `LinkableModel`'s canonical URL is `link_url_pattern` = `/{entity_type_plural}/{public_id}` — keyed on **`public_id`**, the uniform URL identity from [ModelDrivenLinkability.md](../model_driven_metadata/ModelDrivenLinkability.md), _not_ on `slug`. For most entities `public_id` is the slug; for `Location` it's `location_path` (route `/locations/[...path]`).

✅ DONE — the reference-body layer also uses `public_id`: nested referent schemas (`EntityRef`, `TitleRef`, `GameplayFeatureRef`, `ModelRef`, `ModelVariantSchema`, `TitleModelSchema`, `TitleModelVariantSchema`, `RelatedTitleSchema` and subclasses) expose `public_id` rather than a mislabeled `slug`. Location-backed facet refs that already carried `location_path` under `slug` now expose the same value as `public_id`. That means the assembler reads `ref.public_id` uniformly for every target.

To build the URL the assembler needs two facts about the target, both **derivable from the model** (`_meta` + `LinkableModel` ClassVars) and therefore codegen'd, not hand-declared:

- which entity type a given FK / M2M field targets — `field.related_model.entity_type`
- that entity type's URL prefix — `entity_type_plural`, already emitted

Both ride the existing `export_entity_meta` → [`entity-meta.ts`](frontend/src/lib/entities/entity-meta.ts) channel, which ships `entity_type`, `entity_type_plural`, labels, media categories, and the relationship map per entity. The per-entity record keeps the shape cohesive — one object per entity, indexed `ENTITY_META[entityType].relationships[field]`:

```ts
export const ENTITY_META = {
  model: {
    entity_type: "model",
    entity_type_plural: "models",
    label: "Model",
    label_plural: "Models",
    relationships: {
      corporate_entity: { entity_target_type: "corporate-entity", many: false },
      title: { entity_target_type: "title", many: false },
      themes: { entity_target_type: "theme", many: true },
    },
  },
  // ...
} as const;
```

Keys are snake_case to match the file's existing convention (`entity_type`, `entity_type_plural`). The `Relationship` NamedTuple below carries `target_type` and `many`; `many` emits as-is, while the Python `target_type` emits as the TS field `entity_target_type` (named for clarity at the consumer — the one re-cased field). `many` (from `field.many_to_many`) tells the assembler whether the API ships a single ref or a list. `entity_target_type` names any **linkable** target — a catalog entity or another `LinkableModel` such as `user` (see [the linkable boundary](#linkable-crawlable-and-the-id-decision) below) — so it indexes straight back into `ENTITY_META` for the prefix. Canonical-URL construction is two cohesive lookups, no hand-declared prefixes or targets anywhere:

```ts
const rel = ENTITY_META[entityType].relationships[field]; // { entity_target_type: 'corporate-entity', many: false }
const target = ENTITY_META[rel.entity_target_type]; // { entity_type_plural: 'corporate-entities', ... }
const publicId = ref.public_id;
const url = resolveHref(`/${target.entity_type_plural}/${publicId}`); // → absolutized into the @id
```

For `many: true` relations the assembler emits an array of `@id`s; the API must serialize the M2M in a deterministic order (an explicit `order_by` on the relation, not a bare `.all()`) so the emitted `@graph` is byte-stable across requests and stays cache-friendly.

Exporter change — extend the per-`cls` loop in [`export_entity_meta`](backend/apps/catalog/management/commands/export_entity_meta.py) with a `_meta` walk:

```python
class Relationship(NamedTuple):
    target_type: str
    many: bool

# inside the existing per-cls loop:
relationships: dict[str, Relationship] = {}
for f in cls._meta.get_fields():
    if (
        f.is_relation
        and not f.auto_created  # forward FK / M2M only; drop reverse accessors
        and f.related_model
        and issubclass(f.related_model, LinkableModel)  # has a canonical URL
    ):
        relationships[f.name] = Relationship(f.related_model.entity_type, f.many_to_many)
```

`not f.auto_created` is load-bearing: `get_fields()` also returns reverse accessors (e.g. `MachineModel.manufacturer` shows up on `Manufacturer` as a reverse FK), which satisfy `is_relation` + `related_model` and would bloat `relationships` with dozens of unused inverse entries. `f.concrete` is _not_ the right filter — `ManyToManyField` is non-concrete, so it would wrongly drop forward M2M like `themes`.

The target filter is **`LinkableModel`, not `CatalogModel`** — the property that matters for emitting an `@id` is "does this target have a canonical URL?", which is exactly what `LinkableModel` means. Widening the boundary captures cross-references to non-catalog-but-linkable entities (`user`, once it's a `LinkableModel` — see below) with zero special-casing: a `created_by → user` relation resolves through `ENTITY_META` like any other. Targets that aren't `LinkableModel` (internal FKs like `ingest_run`) are dropped — they have no URL, can't be an `@id`, and aren't valid `relationshipMap` targets. One consequence: `ENTITY_META`'s **entry set** spans every concrete `LinkableModel`, so any referenced linkable target has an entry to resolve against. The exporter walks `core.entity_types.all_linkable_models()` — the cross-app `LinkableModel` registry — not just `catalog_models()`, so a non-catalog target like `user` (in `accounts`) gets an entry automatically once `User` becomes a `LinkableModel`; no per-target collection step is needed. This is the **done** rename: the registry is now `entity-meta.ts` / `ENTITY_META` (a linkable-entity registry), not the former catalog-only `model-meta.ts` / `CATALOG_META`.

The filter is deliberately scoped to **forward relations the detail response serializes inline as `EntityRef`s** — not an oversight that omits reverse relations. The generic walk needs the referent's `public_id` to build a URL, and only serialized refs carry one; a reverse accessor `_meta` knows about but the Ninja schema doesn't ship would be a dead entry the assembler can never use. The one inverse relation v1 emits (`Title.workExample` → its Models) is handled by bespoke composition off the embedded `model_detail`, not this walk (see [Single-Model Titles](#single-model-titles)). When the hub-page [`ItemList` follow-up](#schemaorg-itemlist-on-hub-pages) lands and a detail response starts serializing its child set (e.g. `manufacturer.models`), the predicate widens to "forward FK/M2M **plus** reverse relations the response actually carries" — keyed off the response shape, since `_meta` alone can't tell which reverse accessors are exposed.

**Denormalized refs are not in `_meta`, and are deliberately not mapped.** A subtlety the `_meta` walk can't see: some refs on the response aren't the entity's own fields, they're _flattened from a related entity_. `ModelDetailSchema` exposes `manufacturer` (from `corporate_entity.manufacturer` — [machine_models.py:413](backend/apps/catalog/api/machine_models.py#L413)), `franchise` and `series` (from `title.franchise` / `title.series` — [:523-529](backend/apps/catalog/api/machine_models.py#L523-L529)). `MachineModel._meta` has `corporate_entity` and `title`, but **not** `manufacturer`/`franchise`/`series` — so `ENTITY_META.model.relationships` won't contain them. Mapping one in `relationshipMap` would resolve to no entry. That's correct: these are **UI display conveniences, redundant in the `@graph`.** The Model node already emits its direct FK (`corporate_entity → brand`, `title → exampleOfWork`); a consumer reaches the manufacturer by following `corporate_entity`'s `@id` to the CorporateEntity node, and franchise/series by following `title`'s. Emitting them on the Model node too would duplicate a one-hop-discoverable fact. So **`relationshipMap` maps only direct `_meta`-backed fields; flattened convenience refs are omitted** (and an implementer should not try to map `manufacturer`/`franchise`/`series` on `model`). If a specific flattened ref ever genuinely must appear on a node, that one key takes an explicit `{ property, target }` declaration in the per-model file — the escape hatch, used only where transitive discovery isn't enough.

This is the lightest model-driven pattern — a pure `_meta` walk — and a parity test pins the emitted shape (per the codegen rules in [ModelDrivenMetadata.md](../model_driven_metadata/ModelDrivenMetadata.md)). It does **not** revive the deferred [`CatalogRelationshipSpec`](../model_driven_metadata/ModelDrivenCatalogRelationshipMetadata.md): that spec carries claim-resolution metadata (namespace, `identity_fields`, subject) the structured-data layer never reads, and its revival trigger is a second consumer of _that_ metadata. Cross-references consume only FK _targets_, which `_meta` already knows. With this in place, `entity-meta.ts` becomes the model→frontend relationship-shape source; future generic consumers (forms, tables, relationship traversal) read it rather than adding a parallel registry — worth a line in the exporter docstring so the next person doesn't.

#### Linkable, crawlable, and the `@id` decision

Two orthogonal properties decide how a cross-reference is emitted, and they have **different sources** — neither lives in the per-model TS file:

- **Linkable** — the target has a canonical URL. This is a model fact: `issubclass(LinkableModel)`, surfaced by whether the target has a `ENTITY_META` entry at all (the walk above only emits relations to linkable targets, so _inclusion encodes linkability_ — no separate `linkable` boolean is needed).
- **Crawlable** — the target's detail page is server-rendered, so a crawler that follows the `@id` finds a real node (the dereference invariant from [Schema.org IDs](#schemaorg-ids)). This is a **route** fact, not a model fact — it depends on whether the SvelteKit route does an SSR `load`, which Django `_meta` can't see.

The crawlable fact already has a single source of truth: [`route-metadata.server.ts`](frontend/src/lib/route-metadata.server.ts), the classifier that drives `sitemap.xml` and `robots.txt`. The assembler must **read a projection of it, not duplicate it** — relocating crawlability into per-model files would fragment a route-shaped fact (one entity has ~7 routes with differing indexability) and create a second source that drifts from the sitemap. The projection asks the classifier for each entity's _actual_ detail route rather than reconstructing a route ID:

```ts
// entity → is its catalog-detail route search-engine indexable (SSR)?
// Derived from the same classifier the sitemap uses, so it can't drift from it.
const DETAIL_CRAWLABLE: ReadonlyMap<CatalogEntityKey, boolean> = new Map(
  [...catalogRoutesByEntity((c) => c.kind === "catalog-detail")].map(
    ([entity, ids]) => [entity, ids.some(isSearchEngineIndexable)],
  ),
);

export function isEntityDetailCrawlable(entity: CatalogEntityKey): boolean {
  return DETAIL_CRAWLABLE.get(entity) ?? false;
}
```

Do **not** reconstruct the route ID as `/${entity_type_plural}/[slug]`: the public-id segment isn't uniformly `[slug]` (Location's detail route is `/locations/[...path]`), and a future nested detail route would diverge further. Enumerating the classifier's own `catalog-detail` routes sidesteps both.

**Where this runs.** `route-metadata.server.ts` is server-only (it `import.meta.glob`s layout sources), so `isEntityDetailCrawlable` — and therefore entity JSON-LD assembly — must live in a `+*.server.ts` load, not a universal `+page.ts`, or the client build breaks. This is also correct on the merits: crawlers only consume SSR output, so the `@graph` is built server-side and the emit decision (`@id` vs omit) is baked into the serialized data handed to the component.

The two flags drive the emission decision:

| linkable | crawlable | emit                                                                                                                                                                     |
| -------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| ✓        | ✓         | `{"@id": "<url>"}` — the normal catalog cross-reference                                                                                                                  |
| ✓        | ✗         | the `@id` anyway — a valid global identifier that silently starts dereferencing once the page goes SSR — or omit. The choice is the assembler's, not baked into the data |
| ✗        | —         | omit — no URL to point at                                                                                                                                                |

⏸️ DEFERRED (implementation) — every cross-reference target in the wired tranche is a crawlable SSR catalog-detail page, so the `linkable ✓ / crawlable ✗` row never fires yet. `buildSchemaOrgNode` therefore emits `{"@id": …}` for **any linkable target** (any target with an `ENTITY_META` entry), full stop — `isEntityDetailCrawlable` and the omit-branch are not yet built. They land when `User` becomes a `LinkableModel` and the first non-crawlable target (`user`) appears.

**Cross-references are an `@id` or nothing; v1 never emits a name-only blank node here.** A useful blank node would carry the referent's `@type` (`{"@type": "Brand", "name": "Stern"}`), but that type lives in the _referent's_ `schemaOrg.types` — neither `relationshipMap` (property name only) nor `ENTITY_META` (no schema.org types) has it, so a typed blank node would mean cross-loading the referent's `EntityInfo` via the `index.ts` aggregator. v1 has no case that needs it (catalog targets are crawlable → `@id`; `user` is omitted pre-SSR), so the generic walk emits `@id` or omits, full stop, and the cross-load is deferred until a concrete case demands it. (The page-scoped blank nodes elsewhere — team members on `/about/people` — are a different path: the _page_ knows the type and composes them directly, no cross-load.)

**Why a declared relation can't fail to resolve.** The hazard this forecloses: a `relationshipMap` entry whose target has no `ENTITY_META` entry, leaving the assembler to read `relationships[field]` as `undefined` and crash at render. The `LinkableModel` boundary plus the widened entry set removes it structurally — every linkable target has an entry, so any relation the assembler is asked to emit resolves. The one remaining mistake worth a light guard is a `relationshipMap` key that names a _scalar_ field rather than a relation; ✅ DONE — `buildSchemaOrgNode` throws a descriptive `Error` when a declared `relationshipMap` key has no matching `_meta`-backed relationship.

**`user` is the worked example of the split, and is currently mis-declared.** It is linkable in truth — `/users/[username]` exists — but `User(AbstractUser)` is _not_ a `LinkableModel` ([accounts/models.py](backend/apps/accounts/models.py)), and its detail route sits in `SEARCH_ENGINE_NON_INDEXABLE_ROUTE_IDS` (CSR, not crawlable). So today a `created_by → user` reference can't be emitted at all (no entry). Once `User` is promoted to `LinkableModel` the reference becomes emittable as an `@id` (linkable ✓, crawlable ✗ → the assembler may emit the `@id` or omit per the table) — never a blank node, per the rule above. **Prerequisite for any User cross-reference: promote `User` to `LinkableModel`** — which also dovetails with the sitemap's existing "User would need to be a `LinkableModel`" note. Until then, User refs are simply absent.

#### API response audit

The frontend assembler needs raw values, not presentation-shaped ones. Audit findings:

- **Description:** ✅ ships as `RichTextSchema` with four slots — `.text` (authoring markdown, including `[[type:slug]]` reference tokens), `.html` (rendered, tokens resolved to `<a>` tags), `.plain` (backend-flattened prose with tokens resolved and markdown/HTML stripped), and `.citations`. The frontend should use `.plain` for `<meta name="description">`, `og:description`, JSON-LD `description`, and other machine-readable text consumers. Display-limited surfaces still truncate frontend-side per consumer; JSON-LD uses `.plain` untruncated.
- **Image:** ✅ `hero_image_url` is a constructed absolute URL string (`build_public_url(build_storage_key(...))`) — raw enough for the v1 commitment to emit the `display` rendition uniformly.
- **External IDs:** ✅ DONE — raw scalars, not formatted strings, serialized on every owning detail schema: `ipdb_id`/`opdb_id`/`pinside_id` (Model), `fandom_page_id`/`opdb_id` (Title), `opdb_manufacturer_id`/`wikidata_id` (Manufacturer), `ipdb_manufacturer_id` (CorporateEntity), `wikidata_id` (Person). `wikidata_id` and `pinside_id` are 0-populated today (0/582 Person, 0/724 Manufacturer as of 2026-05-28 local DB) but the schema fields and `externalRefs` declarations are in place, so they auto-emit the instant a future ingest fills them — no later code change. (`pinside_id` was retyped from a numeric field to hold the Pinside slug, so its `sameAs` URL resolves.)
- **FK / M2M references:** ✅ ship as public-id-bearing nested refs (`{name, public_id}` plus any display extras) — **no `href`, no type tag**. The referent's canonical URL is constructed frontend-side from `public_id` plus the codegen'd relationship shape — see [Related-entity URLs](#related-entity-urls-from-entity-metats).
- **Top-level detail-schema identity:** ✅ DONE — the **referent** schemas were migrated to `public_id` earlier, and the **top-level** detail schemas now do too: every one inherits `LinkableDetailSchema` and exposes a uniform `public_id` alongside the retained `slug`. The frontend assembler (`buildSchemaOrgNode` in [schema-org.ts](../../../frontend/src/lib/entities/schema-org.ts)) builds the own-`@id` from `entity.public_id`, and `EntityBaseFacts` requires `public_id`. The entity's own `@id` is `/{entity_type_plural}/{public_id}` — a **uniform `public_id`**, never `slug`. Reading `slug` would be a hidden hardcoded rule ("the URL key is always `slug`") that is correct for 8 of 9 widening entities (`public_id == slug`) but **wrong for `Location`**, whose `public_id` is `location_path` on route `/locations/[...path]` — `slug` would emit a non-dereferenceable `@id`. **Location is not special-cased in the assembler** — that would reintroduce the per-type knowledge the model-driven design eliminates.

  **The fix is a single shared base, `LinkableDetailSchema(Schema) { name: str; public_id: str }`**, that every top-level catalog detail schema inherits. `public_id` is sourced from `LinkableModel.public_id` (`slug` for most entities, `location_path` for Location). The assembler reads `entity.public_id` with zero branching, and a **required** `public_id` on the base forces every hand-constructed serializer call to pass it (enforcing sourcing, not just declaration). This base is the backend twin of the frontend's `EntityBaseFacts` contract — both require `public_id`, not `slug`. It's a real shared invariant (uniform `str`, no subclass re-narrows it), so it sits on the right side of the [ApiDesign.md](../../ApiDesign.md) shape-only-base smell test, alongside the blessed `DeletePreviewBase` precedent.

  **Deliberately scoped to `LinkableModel`, not the wider model-base hierarchy.** Do _not_ add parallel `MediaSupportedDetailSchema` / `AliasDetailSchema` / etc. mirroring the Django bases in [DataModeling.md](../../DataModeling.md). The model bases encode behavior + persistence (claims control, soft-delete, wikilink autocomplete, prefetch contracts) — most contribute zero serialized fields, and the one that looks like it'd map, media, actively _mismatches_: image presence on the wire does not track `MediaSupportedModel` membership (`Title` isn't media-supported yet ships `hero_image_url` via child-Model aggregation; `CorporateEntity` is the omit-or-migrate fork). A `MediaSupportedDetailSchema` base would have a membership list contradicting the model's, i.e. a base subclasses fight. Two groupings are identical on both the model and the wire and so earn a shared base: `LinkableModel`'s `{name, public_id}`, and a last-modified timestamp (universal — every catalog entity is `TimeStamped` via `CatalogModel` — one serialized field, membership matching the wire). They stay **separate** concern bases, composed the way the models stack `LinkableModel` + `LastUpdatedModel` (which `SitemappedModel` composes) rather than folding both into one — linkability ("has a canonical URL") and freshness ("when did this last change") are orthogonal, so the timestamp does **not** go on `LinkableDetailSchema`. Per-entity-varying fields (images, aliases, external IDs) stay declared per-schema where they apply. ✅ DONE — the last-modified base (`LastModifiedDetailSchema`) is now on `CatalogDetailSchema`, and its field is **not** raw `updated_at`: it serializes `LastUpdatedModel.last_modified` (the `_last_modified` annotation, see [Last modified](#information-sources)) so JSON-LD freshness and sitemap `<lastmod>` share one definition, including `Title`'s child-Model aggregation. Because that value isn't a literal `updated_at` mirror, the base is named for the concern (`LastModifiedDetailSchema`), not `TimeStampedDetailSchema`.

Completed response-widening for the taxonomy tranche: the backend-owned `description.plain` projection.

Response/codegen prerequisites for richer entity pages:

- ✅ DONE — the relationship-shape codegen above (`relationships` map in `entity-meta.ts`).
- ✅ DONE (backend) — `LinkableDetailSchema` base (`name` + `public_id`) introduced; all 11 named top-level detail schemas + `TaxonomySchema` inherit it, with `public_id` sourced from `LinkableModel.public_id` (`location_path` for Location, `slug` for the rest). A model-driven parity test pins that every linkable entity's detail response carries `public_id`. Deliberately scoped to `LinkableModel`, not the wider model-base hierarchy.
- ✅ DONE (frontend) — `EntityBaseFacts` requires `public_id`, and `buildSchemaOrgNode` builds the `@id` from `entity.public_id` instead of `entity.slug`. No-op for the 11 wired taxonomy entities (`public_id == slug`); the assembler test pins the divergent Location case (`public_id` = `usa/il/chicago`) so the full path is emitted, not a collapsed segment.
- ✅ DONE — external-ID serialization on the owning detail schemas (`wikidata_id` + `opdb_manufacturer_id` on Manufacturer, `ipdb_manufacturer_id` on CorporateEntity, `wikidata_id` on Person; Model/Title already shipped theirs), plus the `externalRefs` declarations and the assembler walk. `wikidata_id`/`pinside_id` are still unpopulated (see External IDs above), but the wiring is in place so emission auto-fires once a future ingest populates them.
- ✅ DONE — a `last_modified` field on its **own** concern base (`LastModifiedDetailSchema`, composed onto `CatalogDetailSchema` alongside `LinkableDetailSchema` — _not_ folded into it; see the audit note above), sourced from `LastUpdatedModel.last_modified` (not raw `updated_at`). Backend: the freshness concept is `LastUpdatedModel.lastmod_expression()` / `last_modified`; the sitemap concern moved off `LinkableModel` to `SitemappedModel(LinkableModel, LastUpdatedModel)`; `register_entity_detail_page` annotates every detail queryset with `lastmod_expression()` (one chokepoint). Frontend: `EntityBaseFacts.last_modified` is required and `buildSchemaOrgNode` emits `dateModified` directly. Sharing the one definition keeps `<lastmod>` and `dateModified` in lockstep and reuses `Title`'s child-Model aggregation; if we ever refine lastmod for content-change accuracy (the claims-churn question), both consumers inherit the fix.

### Per-model frontend info

Each Django model has a companion TypeScript file at `frontend/src/lib/entities/<model-name>.ts` carrying presentation declarations the backend doesn't need to know about — what schema.org type to emit, which fields map to which schema.org properties, etc. This is per the principle that **per-model declarations live where the consumer lives**: backend-relevant knowledge in Django models, presentation-only knowledge in TS.

A Django model's full definition therefore spans two files: the Django class (persistence, validation, URLs, claim machinery) and its companion TS file (schema.org info, and future buckets for any other purely-presentation per-model concern). See [ModelDrivenMetadata.md](docs/plans/model_driven_metadata/ModelDrivenMetadata.md) for the broader principle.

✅ DONE: `frontend/src/lib/entities/types.ts`, `frontend/src/lib/entities/schema-org.ts`, the 11 taxonomy per-model files and `index.ts`, plus `manufacturer.ts`, `system.ts` and the 7 richer-entity files (`corporate-entity.ts`, `series.ts`, `franchise.ts`, `location.ts`, `model.ts`, `title.ts`, `person.ts`). Beyond the no-relation shape (`schemaOrg.types`, canonical `@id`, `name`, untruncated `description.plain`), the assembler walks `fieldMap` (scalar field → schema.org property, with an optional `{ property, transform: 'year' }` value transform) and `relationshipMap` (FK/M2M → cross-reference `@id`s), and `externalRefs` (external IDs → `sameAs`/`identifier`, also driving the visible "External Links" UI — see [External references](#external-references--sameas--identifier)).

**Key naming:** `fieldMap` and `relationshipMap` keys are the entity field names as they appear on the API response — which is the project's snake_case (Django Ninja schemas don't rename fields). `year`, not `releaseYear`. Type-checked via `Partial<Record<keyof TSchema, …>>` against the codegen'd schema, so a serializer convention change (or a renamed Django field) breaks the per-model TS file at compile.

**Shared interfaces** (one place for all per-model files to conform to):

```ts
// frontend/src/lib/entities/types.ts
import type { EntityKey } from "$lib/entities/entity-meta";

export type FieldMapEntry = string | { property: string; transform: "year" };

export interface SchemaOrgInfo<TSchema> {
  types: readonly string[] | ((entity: TSchema) => readonly string[]);
  fieldMap?: Partial<Record<keyof TSchema, FieldMapEntry>>;
  relationshipMap?: Partial<Record<keyof TSchema, string>>;
}

export interface EntityInfo<TSchema> {
  // The canonical ENTITY_META key for this entity — its `entity_type`
  // ('model', 'title', 'corporate-entity', …). This is the ONE key the
  // assembler uses to index ENTITY_META; never the camelCase export name.
  entityType: EntityKey;
  schemaOrg: SchemaOrgInfo<TSchema>;
  // future buckets sit alongside `schemaOrg` as optional fields:
  // openGraph?: OpenGraphInfo<TSchema>;
  // displayCopy?: DisplayCopyInfo<TSchema>;
  // adminAffordances?: AdminAffordancesInfo<TSchema>;
}
```

**Three names, one canonical key.** A model has three distinct identifiers in play: its `entity_type` (`'model'`), its file/export name (`machine-model.ts` → `machineModel`), and — historically — whatever string got passed to `buildSchemaOrgNode`. These must not be conflated: the assembler indexes `ENTITY_META` and resolves `entity_target_type`s using **`entityType` (the `entity_type` value) exclusively**. The export name is just a JS binding; `buildSchemaOrgNode` receives the info _object_, reads `info.entityType`, and never sees a bare string. `EntityKey` (already exported from `entity-meta.ts`) constrains `entityType` to a real key, so a typo or a stale value fails at compile.

**Per-model file:**

```ts
// frontend/src/lib/entities/model.ts
import type { ModelDetailSchema } from "$lib/api/schema";
import type { EntityInfo } from "./types";

export const model: EntityInfo<ModelDetailSchema> = {
  entityType: "model", // the ENTITY_META key
  schemaOrg: {
    types: ["Game", "ProductModel"],
    fieldMap: {
      year: { property: "releaseDate", transform: "year" },
      hero_image_url: "image",
    },
    relationshipMap: {
      corporate_entity: "brand",
      title: "exampleOfWork",
      themes: "genre",
    },
  },
};
```

**Location's per-row schemaOrg.types — same shape, function instead of array:**

```ts
// frontend/src/lib/entities/location.ts
import type { LocationDetailSchema } from "$lib/api/schema";
import type { EntityInfo } from "./types";

export const location: EntityInfo<LocationDetailSchema> = {
  entityType: "location",
  schemaOrg: {
    types: (loc) => {
      switch (loc.location_type) {
        case "country":
          return ["Country"];
        case "state":
          return ["State"];
        case "city":
          return ["City"];
        default:
          // `location_type` is `str | null`; both null and "" land here.
          return ["AdministrativeArea"];
      }
    },
    fieldMap: { short_name: "alternateName" },
  },
};
```

No asymmetry vs other models — `schemaOrg.types` just accepts either form. The function's parameter is typed as `LocationDetailSchema` via the `EntityInfo<LocationDetailSchema>` generic; no extra annotation needed inside the function.

**Type checking and drift detection:**

- The `: EntityInfo<TSchema>` annotation type-checks the whole entry against the contract.
- `Partial<Record<keyof TSchema, …>>` on `fieldMap` (`FieldMapEntry` values) and `relationshipMap` (string values) requires keys to be actual fields of the API schema. A renamed Django field invalidates the per-model TS file after `make codegen` regenerates `schema.d.ts` — TS compile fails until the file is updated. Drift caught at build time without custom validation.

**File layout:**

```text
frontend/src/lib/entities/
├── types.ts            (shared interfaces)
├── schema-org.ts       (shared minimal assembler: type/id/name/description + breadcrumb graph)
├── title.ts
├── machine-model.ts
├── manufacturer.ts
├── corporate-entity.ts
├── person.ts
├── location.ts
├── series.ts
├── franchise.ts
├── system.ts
├── theme.ts
├── gameplay-feature.ts
├── technology-generation.ts
├── technology-subgeneration.ts
├── display-type.ts
├── display-subtype.ts
├── cabinet.ts
├── game-format.ts
├── reward-type.ts
├── tag.ts
├── credit-role.ts
└── index.ts            (optional aggregator)
```

✅ DONE files from the taxonomy tranche: `theme.ts`, `gameplay-feature.ts`, `technology-generation.ts`, `technology-subgeneration.ts`, `display-type.ts`, `display-subtype.ts`, `cabinet.ts`, `game-format.ts`, `reward-type.ts`, `tag.ts`, `credit-role.ts`, plus the shared files listed above. Also `manufacturer.ts` and `system.ts` (the first non-taxonomy entities). The remaining non-taxonomy files in this layout remain future work.

**Consumer access:** route layouts import their specific model directly. A generic consumer (rare today) can use the `index.ts` aggregator for lookup by `entity_type`.

#### Value transformations

Field values shipped raw from the backend often need shape-shifting before they're emitted under a schema.org property. The transforms live in the frontend's `buildSchemaOrgNode` and are declared **locally at the `fieldMap` entry** via the optional tagged form `{ property, transform }`, not inferred from the target property name or the source field type:

- `transform: 'year'` — coerce a year-only integer to a partial ISO 8601 string. `release_year`/`year`/`birth_year`/`death_year`/`year_start`/`year_end` are `PositiveIntegerField`s, not `DateField`s, so `String(year)` yields `"1992"`, which schema.org accepts as a valid partial `releaseDate`/`birthDate`/`foundingDate`/etc. (Full date values, if ever added, ship ISO 8601 from the API and need no transform — a bare-string `fieldMap` entry.)
- A numeric property (`aggregateRating`, etc.) ships as a number from the backend — bare-string entry, no transform.
- A text property sourced from rich text uses the backend's plain projection (`RichTextSchema.plain`). Do not reconstruct prose with a frontend markdown stripper; if a future MarkdownField needs structured-data text, expose the same backend-owned plain projection first.

Local declaration beats both target-name dispatch and source-type dispatch: the codebase has no schema.org target-type system (`releaseDate`-is-a-`Date` isn't represented), and source type alone is ambiguous — an integer could be a year, a count, or an external ID. The author writing `year → releaseDate` already knows it's a date-year, so the intent (`transform: 'year'`) is encoded next to the field. `transform` is a typed union, so a typo fails at compile.

✅ DONE — `buildSchemaOrgNode` normalizes each `fieldMap` entry to `{ property, transform? }` after the null/`undefined`/`''` skip and applies the named transform (`transform === 'year' ? String(value) : value`). First consumers: `MachineModel.year`, `CorporateEntity.year_start`/`year_end`, `Person.birth_year`/`death_year`.

**✅ DONE — `relationshipMap` is walked separately:** for each declared FK / M2M attribute, the assembler reads the referenced public-id-bearing ref from the API response — a single object for an FK, an array when the relationship shape says `many: true` — constructs the referent's canonical URL from `ref.public_id` and the codegen'd relationship shape (see [Related-entity URLs](#related-entity-urls-from-entity-metats)), and emits `{"@id": "https://flipcommons.org/..."}` under the declared schema.org property. Unlike `fieldMap`, this doesn't go through value transforms — the relationship value is always an `@id` reference, never a scalar.

✅ DONE — most glossary entities (the flat taxonomy classes) don't need any field-mapped properties — name and description are everything schema.org wants from them; their per-model TS files omit both `fieldMap` and `relationshipMap`. The two hierarchical ones, `Theme` and `GameplayFeature`, declare a self-referential `relationshipMap` (`parents → isPartOf`) and otherwise omit `fieldMap`.

### Schema.org IDs

Every emitted node's `@id` is the canonical URL of the page that represents it.

- **Entity nodes**: `LinkableModel.get_absolute_url()` (`https://flipcommons.org/models/medieval-madness`, `https://flipcommons.org/people/pat-lawlor`, etc.)
- **Static page nodes**: the page's hardcoded canonical URL (`/about` as `AboutPage` → `@id: "https://flipcommons.org/about"`)
- **Home page node**: `WebSite` at `@id: "https://flipcommons.org/"`

The same `@id` is used everywhere the node appears: primary node on its own page, cross-references from other entities (`exampleOfWork`, `brand`, `manufacturer`, etc.), `itemListElement.item` entries in `BreadcrumbList`. References resolve across pages because every emission of the same entity uses the same canonical URL — fetch the URL, find the full node.

**One exception:** `BreadcrumbList` nodes are emitted without `@id` (JSON-LD blank nodes). They're page-scoped, never referenced from anywhere else, so an identifier serves no purpose.

**We don't use fragments:** We don't use URL fragments for the page-vs-thing distinction. Schema.org allows separating `https://flipcommons.org/models/medieval-madness` (the page) from `https://flipcommons.org/models/medieval-madness#machine` (the thing) via the `WebPage` + `mainEntity` pattern. We don't — we emit only entity nodes (no `WebPage` wrappers), so the page-vs-thing tension never arises and fragments add nothing. Google's rich results work identically either way.

#### Single-Model Titles

[`SingleModelTitles.md`](SingleModelTitles.md) defines a UI collapse rule: when a Title has exactly one Model with no variants, the Title page (`/titles/[slug]`) presents merged content from both entities and `/models/[slug]` redirects to it. The data model is unchanged — two entities, two ChangeSet histories, two IDs — only the UI collapses.

On single-model titles, because `/titles/[slug]` is the place to surface information about both the model and the title, it must emit **both** the Title node _and_ the Model node — in the same `@graph`:

```json
{
  "@graph": [
    {
      "@type": "Game",
      "@id": "https://flipcommons.org/titles/doctor-who",
      "name": "Doctor Who",
      "workExample": {"@id": "https://flipcommons.org/models/doctor-who"},
      ...title-tier fields (name, abbreviations, franchise, series; externalRefs for the Title: fandom_page_id → sameAs, opdb_id → identifier)
    },
    {
      "@type": ["Game", "ProductModel"],
      "@id": "https://flipcommons.org/models/doctor-who",
      "exampleOfWork": {"@id": "https://flipcommons.org/titles/doctor-who"},
      "name": "Doctor Who",
      ...model-tier fields (description, manufacturer, releaseDate, gameplay/technology cross-references; externalRefs for the Model: ipdb_id/pinside_id → sameAs, opdb_id → identifier)
    },
    {
      "@type": "BreadcrumbList",
      ...
    }
  ]
}
```

A crawler following `@id: /models/doctor-who` hits the redirect, lands at `/titles/doctor-who`, parses the `@graph`, and finds the Model node at exactly that `@id`. The dereference invariant from [Schema.org IDs](#schemaorg-ids) holds.

**Property sourcing follows SingleModelTitles.md's field-overlap rules**, but at the per-node level (not merged into one node):

- Title node carries: `name`, abbreviations, franchise, series, `sameAs` for Title's external IDs (`opdb_id`, `fandom_page_id`)
- Model node carries: `description` (the live one, per the field-overlap rule; Title's description is dormant for single-Model and not emitted), `manufacturer`, `releaseDate`, gameplay/technology cross-references, `sameAs` for Model's external IDs (`ipdb_id`, `opdb_id`, `pinside_id`)

**Cross-references stay stable across transitions.** A Person credited on the Model always points at `/models/X` as `@id` — whether the Title is currently single-Model or multi-Model, the Model's identity is unchanged. No reference re-emission needed when collapse status changes.

**On transition to multi-Model:** the JSON-LD shape stays identical. The existing Title node stays, the existing Model node stays, additional Model nodes get added to the catalog (each at its own canonical URL, emitted on its own detail page). Zero shape change for existing entities.

**Title `workExample` references:** the Title node carries `workExample` references to all its Models (just one in the single-Model case, multiple later). This is the inverse of the Models' `exampleOfWork` and gives consumers a one-hop path from the Title to discover all its product variants.

**Edit history and sources** retain per-entity identity. `/titles/X/edit-history` is a CollectionPage about the Title (`@id: /titles/X`); `/models/X/edit-history` is a CollectionPage about the Model (`@id: /models/X`). Distinct `about` targets, no ambiguity. (See [Entity meta-pages](#entity-meta-pages) for the typing.)

**Composition is the frontend's job.** Both entity nodes are assembled in TypeScript by `buildSchemaOrgNode()` (see [Backend vs frontend responsibilities](#backend-vs-frontend-responsibilities)) from the entity facts on the API response. The single-Model case requires only one frontend-specific composition decision: `/titles/[slug]`'s layout passes the embedded Model facts through the assembler as well as the Title's, when present:

```ts
import { title, machineModel } from "$lib/entities";

const graph = [buildSchemaOrgNode(data, title)];
if (data.model_detail) {
  graph.push(buildSchemaOrgNode(data.model_detail, machineModel));
}
graph.push(buildBreadcrumbList(crumbs));
```

The second arg is the per-model info _object_ (`title`, `machineModel`), not a string. `buildSchemaOrgNode` reads `info.entityType` (`'title'`, `'model'`) to index `ENTITY_META` — so the camelCase export name `machineModel` never has to match the `entity_type` `'model'`.

The trigger condition (`data.model_detail` populated) already exists — `TitleDetailSchema.model_detail` is populated inline only for single-Model Titles, per SingleModelTitles.md. The frontend's rule is "if the API embedded the Model, assemble its node too." Same `buildSchemaOrgNode()` machinery as any other entity — no special path.

## External references → `sameAs` / `identifier`

✅ DONE. External-database identities are emitted via a per-entity `externalRefs` registry. The same
registry is the single source of truth for **both** the JSON-LD identities and the visible "External
Links" UI — components render links from it rather than hardcoding URLs in markup.

### Why not a flat global map

The original sketch was a single global `{ fieldName: urlPrefix }` constant. That can't work: the
same field name resolves differently per entity (a Title's `opdb_id` is an OPDB _group_; a Model's
is a _machine_), and some stored IDs aren't URL-addressable at all. So the declaration is
**per-entity**, co-located with the entity's other `SchemaOrgInfo`.

### The registry

Each entity declares `externalRefs` keyed by API field name, with values of type `ExternalReference`
(`frontend/src/lib/entities/types.ts`):

```ts
externalRefs?: Partial<Record<keyof TSchema, ExternalReference>>;

type ExternalReference =
  | { label: string; urlTemplate: string } // resolvable: `{id}` ← stored value
  | { identifier: string }; // non-resolvable id, no buildable URL
```

- `{ label, urlTemplate }` — a resolvable reference. `{id}` is replaced by the stored value to make
  a URL, emitted as JSON-LD `sameAs` and as a visible link labelled `label`.
- `{ identifier }` — a machine-readable id with no URL we can build from what we store. Emitted as a
  schema.org `PropertyValue` (`propertyID` ← `identifier`); no visible link. Graduates to
  `{ label, urlTemplate }` with zero consumer churn once we ingest the resolvable form.

### The two consumers

- `externalLinks(entity, info)` (`external-links.ts`) — returns `ExternalLink[]` for the UI;
  resolves `urlTemplate`, skips `identifier`-only and empty values. Pages compose across entities,
  e.g. a Title page shows its Model's IPDB/Pinside links plus the Title's Fandom link.
- `buildSchemaOrgNode` (`schema-org.ts`) — walks the same registry to emit the `sameAs` array and
  `identifier` `PropertyValue`s on the entity node.

Both apply the same skip rule (`null` / `undefined` / `''`), so the visible links and the
structured-data identities can never drift apart. Keys are `keyof TSchema`, so a renamed or removed
API field fails `svelte-check` rather than silently dropping a reference. Output is always an array
(declaration-ordered), keeping the `@graph` byte-stable and cache-friendly.

### Emission today

| Entity.Field                           | Emits                 |
| -------------------------------------- | --------------------- |
| Model.`ipdb_id`                        | `sameAs`              |
| Model.`opdb_id`                        | `identifier` (`OPDB`) |
| Model.`pinside_id`                     | `sameAs`              |
| Title.`fandom_page_id`                 | `sameAs`              |
| Title.`opdb_id`                        | `identifier` (`OPDB`) |
| Manufacturer.`opdb_manufacturer_id`    | `identifier` (`OPDB`) |
| Manufacturer.`wikidata_id`             | `sameAs`              |
| CorporateEntity.`ipdb_manufacturer_id` | `identifier` (`IPDB`) |
| Person.`wikidata_id`                   | `sameAs`              |

OPDB ships as `identifier` because its public URLs key off an internal autoincrement we don't store;
ingesting that numeric id would flip `opdb_id` to a `sameAs` `urlTemplate` with no consumer change.
`wikidata_id` and `pinside_id` are 0-populated today but declared now so they auto-emit once a future
ingest fills them.

## Types of pages

### Entity detail pages

Such as `/titles/[slug]`, `/models/[slug]`, `/people/[slug]` etc.

Target shape for every SSR entity detail page: each page emits two top-level nodes in `@graph`:

- The entity itself as a typed node (`Game`, `Person`, `Organization`, etc.) with `@id` cross-references to related entities and `sameAs` links to external IDs. No `WebPage` wrapper — the type is the thing, not the medium.
- A `BreadcrumbList` node carrying the page's hierarchical trail. Google's BreadcrumbList rich result replaces the URL in SERPs with a readable trail, measurably lifting click-through. Example chains: Title page → `Home › Godzilla`; Model page → `Home › Godzilla › Godzilla Pro` (Model's parent is its Title; there's no `/models` listing page, and we skip `/titles` since it's CSR-only and an empty shell to crawlers). The JSON-LD chain is richer than the visible UI breadcrumb — that's allowed by Google's policies as long as every item in the chain is a real, accessible page reflecting the site's genuine hierarchy.

✅ DONE for taxonomy detail pages: Theme, GameplayFeature, TechnologyGeneration, TechnologySubgeneration, DisplayType, DisplaySubtype, Cabinet, GameFormat, RewardType, Tag and CreditRole now emit the entity node plus a `Home › {name}` `BreadcrumbList`. Most omit cross-references, images and `sameAs`; `Theme` and `GameplayFeature` additionally emit `parents → isPartOf` cross-references. ✅ DONE for Manufacturer (`Brand`, with `logo`/`url` via `fieldMap`), System (`CreativeWork`, with `manufacturer → producer`) and the 7 richer entities (CorporateEntity, Series, Franchise, Location, MachineModel, Title, Person — see the top-of-section DONE entry for per-entity types and the Model/Location breadcrumb enrichment + Title dual-node composition). `sameAs` and `primary_image`-sourced images await later tranches.

### Entity meta-pages

Every catalog entity has `/[entity]/[slug]/edit-history` and `/[entity]/[slug]/sources`.

Each will emit a `CollectionPage` typed node with `about` → the entity's `@id`. The page is about the entity but its primary content is the collection (of ChangeSets / sources), so `CollectionPage` is more precise than plain `WebPage`, and `about` is more accurate than `mainEntity` (the entity isn't the page's primary subject; the collection is).

For single-Model Titles, the Model's `/models/[slug]/edit-history` and `/models/[slug]/sources` remain accessible even though `/models/[slug]` itself redirects (per SingleModelTitles.md). Each meta-page points `about` at its own entity's `@id`: `/titles/[slug]/edit-history` is about the Title (`@id: /titles/[slug]`), `/models/[slug]/edit-history` is about the Model (`@id: /models/[slug]`). Each entity retains its identity regardless of collapse status (see [Single-Model Titles](#single-model-titles)), so meta-pages have unambiguous about-targets — no collision between Title-side and Model-side history pages.

These pages emit the same `BreadcrumbList` node pattern as entity detail pages, with the trail extended one level (`Home › Godzilla › Godzilla Pro › Edit history`).

### Static pages

Static pages use the same `<head>` / OG / Twitter primitive as entity pages, but with hand-authored values. No model derivation because there's no model. Each page also emits a `BreadcrumbList` node.

#### / ✅ DONE

`WebSite` node. No `BreadcrumbList` — the home page is the root.

No `SearchAction` despite Google's sitelinks-searchbox hook: the search endpoint is CSR, so declaring a SearchAction would lie to crawlers that don't execute JS. Revisit if/when `/search` goes SSR.

#### /about ✅ DONE

`AboutPage` (a `WebPage` subtype). `BreadcrumbList`: `Home › About`.

#### /about/people ✅ DONE

`CollectionPage` (the page presents a collection of team members; `AboutPage` is taken by `/about`, `ProfilePage` is single-person). `BreadcrumbList`: `Home › About › People`.

Persons attach to the `CollectionPage` via its `about` property — `about` is `Thing`-typed (Person qualifies) whereas `hasPart` is `CreativeWork`-typed (Person does not). Each Person is a blank node (no `@id`; page-scoped, never referenced).

If/when team members get FlipCommons User accounts and User pages go SSR, the User's canonical URL becomes their `@id`; the blank-node interim is a stopgap. Future: a FlipCommons `Organization` node (likely on `/`) could carry `founder` references to the same Persons.

#### /privacy, /terms, /licensing ✅ DONE

Plain `WebPage` (no specific subtype fits). `BreadcrumbList[Home, [page name]]`. Treated as top-level peers of About, not children — the legal pages live under SvelteKit's `(legal)` layout group, not under `/about`.

### CSR pages: out of scope

Most crawlers don't execute any of the JavaScript on the pages they fetch. Pages rendered client-side after page load (CSR) emit `<head>` content the crawler doesn't see. Google crawler _does_ execute JS and _may_ pick up CSR-rendered metadata, but coverage and reliability are worse than SSR.

Because of this, we don't include CSR pages in `sitemap.xml`.

The following page categories are currently CSR and therefore will probably be excluded from the first pass implementation of this doc's design.

#### Entity listing pages

Such as `/titles`, `/models`, `/people`.

Currently CSR and thus not crawlable.

#### User detail pages

`/users/[username]`. Shows the user's contributions and edit history.

Currently CSR and thus not crawlable.

#### Authenticated CRUD pages

`/[entity]/new`, `/[entity]/[slug]/edit`, delete confirmation screens.

CSR by design: they require login and will never be crawlable.

## Model-driven metadata enhancements

### MediaSupportedModel

Exists at [apps/media/models/base.py](backend/apps/media/models/base.py). Needs a `primary_category` ClassVar and a `primary_image` resolver. **Today only `MachineModel`, `Manufacturer`, `Person` and `GameplayFeature` inherit `MediaSupportedModel` and declare `MEDIA_CATEGORIES`** — `Title`, `CorporateEntity`, `Series`, `Franchise` and the taxonomy classes do **not**, so they have no own media and `primary_image` doesn't apply to them as-is (see the fork below).

```python
class MediaSupportedModel(ClaimControlledModel):
    MEDIA_CATEGORIES: ClassVar[list[str]] = []
    primary_category: ClassVar[str | None] = None

    @property
    def primary_image(self) -> EntityMedia | None:
        """The is_primary EntityMedia row in this entity's primary category, or None.

        Reads from the `primary_media` prefetch attribute, mirroring the
        discipline of `apps/media/helpers.py:primary_media(entity)`. Raises
        if the prefetch wasn't loaded — never silently queries during
        serialization (which would N+1 in list / sitemap / image-extension
        contexts where many entities serialize at once).

        Callers that need primary_image must use the queryset path that
        prefetches it; that path is shared with the existing primary_media
        helper and tested.
        """
        if self.primary_category is None:
            return None
        prefetched = getattr(self, "primary_media", None)
        if prefetched is None:
            raise ImproperlyConfigured(
                f"{type(self).__name__} was not loaded with the primary_media "
                f"prefetch; primary_image cannot be resolved at serialization time"
            )
        for em in prefetched:
            if em.category == self.primary_category and em.is_primary:
                return em
        return None

    class Meta:
        abstract = True
```

Each media-supported subclass declares its `primary_category`. The ones that inherit `MediaSupportedModel` today:

- `MachineModel` → `"backglass"`, `Manufacturer` → `"logo"`, `Person` → `"portrait"`.

**Entities that are not media-supported need an explicit decision, not an assumed `primary_category`.** This is a real fork, because `Title` and `CorporateEntity` — both of which want a structured-data image — don't have own media today:

- **`Title`** has no own backglass; its hero image is aggregated from its child Model's media via the existing `extract_image_urls` path (which already ships `hero_image_url`). **v1 keeps that path** — a Title's JSON-LD/OG image comes from the child Model, not a Title `primary_image`.
- **`CorporateEntity`** has no logo media of its own. Either migrate it onto `MediaSupportedModel` (add the base + `MEDIA_CATEGORIES = ["logo", ...]`, mirroring `Manufacturer`) or omit its image until then.

So: **either migrate the entities whose JSON-LD wants an image (`Title`, `CorporateEntity`, …) onto `MediaSupportedModel`, or keep the existing per-entity image source** (Title aggregation; CorporateEntity omitted). v1 JSON-LD does **not** require `primary_image` — layouts already receive `hero_image_url` — so this is an enhancement decision, not a v1 blocker. The `primary_category` examples above are only valid for entities that actually inherit the base.

**Prefetch contract:** `primary_image` is a deliberate consumer of the existing `primary_media` prefetch pattern in [`apps/media/helpers.py`](backend/apps/media/helpers.py). It NEVER queries during serialization — it reads from the prefetched attribute, asserting presence and failing loudly if absent. This preserves the N+1-safety discipline that the existing `primary_media(entity)` helper enforces. List contexts that need `primary_image` (sitemap image extensions, list endpoints emitting image URLs, etc.) must use the optimized queryset path that includes the prefetch; that path is shared with the existing helper.

**URL emission:** when the metadata layer needs the image's URL, it resolves through the `display` rendition: `build_public_url(build_storage_key(em.asset.uuid, "display"))`. The three pre-generated renditions (`original`, `thumb`, `display`) already exist on every asset; `display` is the right size for OG / Twitter / JSON-LD / sitemap consumers in v1. Per-consumer aspect-ratio crops are a [Bunny-Optimizer follow-up](#bunny-optimizer-driven-aspect-ratio-crops).

## Follow-ups

Not for v1.

### Sitemap image extension

The standard sitemap (URLs + `<lastmod>`, model-driven via `LinkableModel` walk, emitted through [super-sitemap](https://github.com/jasongitmail/super-sitemap)) is in v1. The image extension (`<image:image>` per URL, declaring associated images with title and caption) is deferred.

Why deferred: super-sitemap doesn't support sitemap extensions and exposes no plugin/hook for them. Adding image extension means either patching super-sitemap, replacing it, or rolling a separate `/sitemap-images.xml` endpoint and referencing it from the sitemap index. The separate-endpoint approach is the cleanest — keeps the existing super-sitemap pipeline untouched, uses the same per-entity facts (`primary_image` via the `display` rendition URL, entity name as image title, entity description as image caption), and slots into the sitemap index as a sibling.

Why valuable: highest-leverage hook for Google Image Search on a visual encyclopedia. Visual catalog content (backglass art, playfield photos, cabinet shots) is exactly the use case `<image:image>` was designed for, and pinball search has real image-driven discovery (someone searching "medieval madness playfield" lands via Google Images more often than via web search).

Not blocking for v1 because the in-page metadata (JSON-LD `image`, OG `og:image`) already gives Google enough signal to index the images. The image-extension lift is incremental SERP quality, not foundational discoverability.

### Bunny-Optimizer-driven aspect-ratio crops

The media pipeline already produces three pre-generated renditions per asset (`original`, `thumb`, `display` — see [apps/media/models/rendition.py](backend/apps/media/models/rendition.py)). For v1, every metadata representation emits the `display` rendition URL via `build_public_url()`, which gives reasonable preview quality across consumers without further infrastructure.

What Bunny Optimizer would add on top is **per-consumer aspect-ratio crops**, since the pre-generated renditions are single-aspect (whatever the source asset's aspect ratio is). Facebook recommends OG previews at 1200×630 (1.91:1); Twitter's `summary_large_image` wants 1200×675 (16:9); Google rich results' richest eligibility comes from providing multiple ratios (1:1, 4:3, 16:9). The `display` rendition is approximately the right size but not the right shape for every consumer's preview card.

[Bunny Optimizer](https://bunny.net/optimizer/) adds URL-driven transforms on top of the existing CDN — `?width=1200&height=630&aspect_ratio=16:9` produces the requested crop on demand, cached at the edge. With it enabled, the metadata layer could emit consumer-tailored URLs:

- OG `og:image` → `?width=1200&height=630` (Facebook 1.91:1)
- Twitter `twitter:image` → `?width=1200&height=675` (Twitter 16:9)
- Sitemap `<image:loc>` → `?width=1200` (long-side, native aspect)
- JSON-LD `image` → richer `ImageObject[]` with multiple aspect-ratio entries

The lift is real but not urgent — `display` is good enough that v1 is shippable without it. Defer until SERP / share-card quality becomes a measurable concern.

### Auto-generated per-machine OG share images

Pinball is shared heavily in hobbyist communities — Discord servers, Reddit forums, Slack groups, group chats. Unique per-entity preview cards composited at publish time would meaningfully change how those shared links look: backglass art + machine name + manufacturer + year + subtle Flipcommons branding. Makes the site read as archival, premium, authoritative — the social-media analogue of JSON-LD's "first-class structured data" framing.

Implementation paths to compare when the time comes:

- Server-rendered with Satori / `@vercel/og` style libraries
- One-time render at publish, store in iDrive e2 alongside other media
- The latter fits the existing media pipeline more cleanly

This is independent of Bunny Optimizer (those are crops/renditions of existing images; this is composited custom artwork).

### Schema.org `ItemList` on hub pages

Entity hub pages (Manufacturer → list of Models, Theme → list of Models, Series → list of Titles, etc.) currently emit just the entity node. The inverse cross-references on each Model already make the relationship discoverable, but LLMs answering aggregate questions ("what did Stern make in the 90s?") have to crawl 50 Model pages to assemble the answer rather than reading one Manufacturer page.

If aggregate-query performance turns out to be poor in practice, add an `ItemList` node in the hub page's `@graph` with `itemListElement` references (just `@id` URLs, not inlined nodes) to each related entity. Cheap payload (URLs only); meaningful LLM lift. Skip preemptively in v1 — add when the need is concrete.

### User and listing pages

Already documented under [CSR pages: out of scope](#csr-pages-out-of-scope). Both categories require SSR conversion before metadata work applies. When SSR'd:

- User detail pages → `ProfilePage` typing, Person body node, sameAs to external profiles, in the sitemap (User would need to be a `LinkableModel`)
- Catalog entity listing pages → `CollectionPage` typing, `ItemList` of `@id`-referenced entities

The metadata design for these is sketched in the CSR section; the gating concern is the SSR conversion itself.
