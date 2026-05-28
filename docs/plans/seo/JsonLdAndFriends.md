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

This project emits all three on entity detail pages. Each layout hand-picks the relevant fields (title, description, hero image, alt text) and passes them in. Listing pages emit `<title>` only (no description, no canonical) because they're CSR.

✅ DONE — taxonomy, Series and Franchise detail layouts source their meta/OG descriptions from `RichTextSchema.plain` via `metaDescriptionFor(profile)`, so markdown syntax and `[[type:slug]]` reference tokens do not leak into machine-readable descriptions.

### Open Graph

Open Graph (OG) is de facto link-preview standard: Facebook, LinkedIn, iMessage, Slack, Discord, Bluesky, Mastodon (and Twitter as a fallback) all read OG.

It uses `<meta property="og:*">` tags in `<head>`. Small fixed property set per page — `og:type`, `og:title`, `og:description`, `og:image`, `og:url`, `og:site_name`. `og:type` draws from a small vocabulary (`article`, `profile`, `website`, etc.).

This project emits `og:type`, `og:site_name`, `og:title`, `og:description`, `og:url`, `og:image` and `og:image:alt`. Remaining gaps:

- ✅ DONE — `og:type` now per-page (see [Open Graph page types](#open-graph-page-types)); Person/User layouts emit `profile`, static pages emit `website`, default is `article`.
- TODO — `og:image:alt` is built per-layout as `` `${entity.name} pinball machine` `` — wrong for Person, Manufacturer, CorporateEntity (a designer is not a pinball machine).
- TODO — listing pages emit nothing (CSR; see [CSR pages: out of scope](#csr-pages-out-of-scope)).

### Twitter card

`<meta name="twitter:*">` tags that Twitter uses to control previews on its site. Twitter cascades from OG when Twitter-specific tags are absent, so the only one worth emitting is `twitter:card`.

✅ DONE — remove redundant `twitter:title` / `twitter:description` / `twitter:image` / `twitter:image:alt`; keep only `twitter:card`. `twitterCardType()` selects `summary_large_image` when an image is present, else `summary`.

TODO — once entity layouts migrate to [`MediaSupportedModel.primary_image`](#mediasupportedmodel), wire the image source through there instead of the per-layout `image` prop. Selection logic itself stays the same.

### JSON-LD

A JSON document inside `<script type="application/ld+json">` in `<head>`, using vocabularies from [schema.org](https://schema.org). Consumed by search engines for rich results and knowledge panels, by LLM crawlers for citation accuracy and by other databases linking in via `sameAs`. Each page emits a `@graph` of one or more typed nodes (`Game`, `Person`, `Organization`, etc.) with `@id` cross-references to related entities and `sameAs` to external IDs. The highest-fidelity representation — arbitrarily rich, nested and addressable.

✅ DONE — static pages (`/`, `/about`, `/about/people`, `/privacy`, `/terms`, `/licensing`) emit JSON-LD via the [`JsonLd.svelte`](frontend/src/lib/components/JsonLd.svelte) component and [`jsonld.ts`](frontend/src/lib/components/jsonld.ts) helpers (`jsonLdGraph`, `webSite`, `pageNode`, `breadcrumbList`).

✅ DONE — taxonomy detail pages emit JSON-LD: Theme, GameplayFeature, TechnologyGeneration, TechnologySubgeneration, DisplayType, DisplaySubtype, Cabinet, GameFormat, RewardType, Tag (`DefinedTerm`) and CreditRole (`Occupation`). Each graph contains the entity node plus a page-scoped `BreadcrumbList`; descriptions come from backend `RichTextSchema.plain` and are not truncated. Rendering is gated to the detail route, not `/edit-history` or `/sources`.

TODO — richer non-taxonomy entity detail pages (Title, MachineModel, Manufacturer, CorporateEntity, Person/User, Location, Series, Franchise, System) and entity meta-pages.

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

† Location will be a specific type of Place: AdministrativeArea, Country, State, or City. See the Location example in [Per-model frontend info](#per-model-frontend-info).

## Open Graph page types

| Page                                                            | `og:type` |
| --------------------------------------------------------------- | --------- |
| Home (`/`) and legal pages (`/privacy`, `/terms`, `/licensing`) | `website` |
| Person and User detail pages                                    | `profile` |
| Everything else                                                 | `article` |

"Everything else" includes all other catalog entity detail pages (Title, MachineModel, Manufacturer, CorporateEntity, Location, Series, Franchise, System, Theme, all taxonomy classes), all entity meta-pages (`/edit-history`, `/sources`), and the prose static pages (`/about`, `/about/people`).

Legal pages get `website` rather than `article` because they aren't articles in OG's editorial sense — no author, no published date, no section. `website` is the honest "we don't have a better type for this." `/about` and `/about/people` stay `article` because they're editorial-style prose describing the project and team.

`article` isn't a perfect semantic match for any of those (a Manufacturer isn't an article, a taxonomy term isn't an article), but it's the closest of OG's available choices and it's at least less wrong than calling everything a `website`. The Person → profile case is the one genuine fit and the one place dynamic typing pays off — Facebook and LinkedIn render profile-card previews differently from article previews, so designer/artist pages get a small but visible improvement when shared on social.

No per-entity declaration in the per-model TS files. The mapping is a central function keyed off whether the page is the home page, whether the entity's `schemaOrg.types` contains `Person`, and a default of `article`. About 10 lines.

✅ DONE (static + Person/User layouts) — `MetaTags.svelte` accepts an `ogType` prop with `article` default; static pages and `/people/[slug]` set the right value explicitly. Remaining catalog entity layouts (Title, MachineModel, Manufacturer, etc.) still inherit the `article` default — correct per the table, no further work needed there.

We deliberately don't use `product` (Facebook's extension) for MachineModel — it's commerce-oriented (price, availability, SKU) and we're not selling machines.

## Architecture

### Autogenerated representations

We will automatically generate these different machine-readable representations based on information in the Django models, as per [ModelDrivenMetadata.md](docs/plans/model_driven_metadata/ModelDrivenMetadata.md).

The same facts feed all of these machine-readable representations. 90% of this information is already well-described by the model and won't require additional per-model mapping information.

#### Information sources

Some come from the Django model (backend), some from the per-model TS file ([see below](#per-model-frontend-info)):

- **Canonical URL** — `LinkableModel.get_absolute_url()` (backend; already in API responses)
- **Display name** — `LinkableModel.name` (backend)
- **Description** — `RichTextSchema.plain`, a backend-flattened prose projection of the entity's markdown description. Frontend display consumers truncate it per surface: `<meta name="description">` ~155 chars (Google SERP display limit), `og:description` ~200 chars (Facebook/LinkedIn preview cards), `twitter:description` ~200 chars (when emitted; usually cascades from OG). JSON-LD `description` is **not truncated** — machine-readable consumers (LLMs, search engines, linked-data crawlers) benefit from the full text and have no display constraint.
- **Primary image** — [`MediaSupportedModel`](#mediasupportedmodel)`.primary_image`: primary image of primary category. Emitted as the `display` rendition's absolute URL via `build_public_url(build_storage_key(asset.uuid, "display"))` on the backend; shipped as a URL string on the API response. Same URL used across JSON-LD `image`, OG `og:image`, Twitter `twitter:image` and sitemap `<image:loc>`. Aspect-ratio crops per consumer are a [Bunny-Optimizer follow-up](#bunny-optimizer-driven-aspect-ratio-crops); v1 uses one rendition for all.

  **Deliberate exception to "presentation lives frontend-side":** the choice of which rendition to emit (`display` vs `thumb` vs `original`) is a presentation decision, but it's encoded in the Python `build_public_url(... "display")` call rather than in TS. The CDN base URL (`MEDIA_PUBLIC_BASE_URL`) is server-side config that isn't (and shouldn't be) exposed to the frontend, so URL construction has to happen backend. We could ship the asset's UUID + rendition_type and have TS build the URL — but that means duplicating the base URL into frontend env, and the storage layer's URL conventions naturally belong with the storage layer. Net: one small backend presentational decision (rendition selection), justified by where the URL construction primitive lives.

  **Frontend static assets** (`/og-default.png`, future auto-composited share images stored under `static/`) are a separate path — absolutize via `lib/utils.absoluteAssetUrl(path, pageUrl)`, which routes through SvelteKit's `asset()` and the URL constructor so a configured CDN base or empty-base local dev both work. Backend-served images already arrive absolute and skip this helper.

- **Last modified** — `TimeStampedModel.updated_at` (backend)
- **Schema.org types** — declared in the per-model TS file's `schemaOrg.types` field. Static array for most entities; per-row function for Location. See [Per-model frontend info](#per-model-frontend-info).
- **Cross-references** — declared in the per-model TS file's `schemaOrg.relationshipMap`. Each declared FK / M2M attribute carries **only** its schema.org property name (`corporate_entity → brand`, `title → exampleOfWork`, `themes → genre`, etc.) — that name is presentation vocabulary Django can't express. The referent's canonical URL is _not_ declared here; it's constructed from the codegen'd relationship shape (see [Related-entity URLs](#related-entity-urls-from-catalog-metats)). The frontend metadata builder walks the declared set and emits an `@id` reference to the referent's canonical URL under the declared property. Undeclared relationships are not emitted.
- **External-system identity** — small hand-edited TS constant mapping specific field names (`wikidata_id`, `opdb_id`, `ipdb_id`, `opdb_manufacturer_id`, `ipdb_manufacturer_id`) to URL templates. Field-name-based, not prefix-based — `ipdb_rating` is a number stored on our model, not an ID, and won't accidentally match. Each present, non-null field becomes a `sameAs` entry.

### Backend vs frontend responsibilities

All metadata assembly — JSON-LD, head, OG, Twitter — lives in the frontend. Backend ships raw entity facts; the frontend reads them plus per-model declarations from [`frontend/src/lib/models/`](#per-model-frontend-info) and emits the metadata.

#### Backend's job

Serve raw entity facts on the entity detail API response: `name`, `description` (`RichTextSchema`, including backend-rendered `.plain`), `hero_image_url` (the `display` rendition's absolute URL), `updated_at` (ISO 8601), FK / M2M references as `EntityRef` (`{name, slug}` — no `href`; the frontend constructs canonical URLs, see [Related-entity URLs](#related-entity-urls-from-catalog-metats)), external-ID scalars (`ipdb_id`, `opdb_id`, `wikidata_id`, etc.). Mostly what's already shipped today; see [API response audit](#api-response-audit) below.

#### Frontend's job

- **Hold per-model presentation declarations** in [`frontend/src/lib/models/<model-name>.ts`](#per-model-frontend-info) — one file per Django model, containing the schema.org types, field map, relationship map, and any other purely-presentation per-model info. ✅ DONE for the taxonomy tranche's 11 entities.
- **Assemble the SchemaOrgNode** for each entity via a generic `buildSchemaOrgNode(entity, modelInfo)` function that walks the declarations against the entity facts. ✅ DONE for the minimal no-relation shape (`@type`, `@id`, `name`, untruncated `description.plain`); TODO to widen for field maps, relationship maps, images and `sameAs`.
- **Compose the `@graph`** per page — pick which nodes go in (entity node always; Model node for single-Model Titles when `data.model_detail` is present; `BreadcrumbList`; `CollectionPage` for meta-pages).
- **Apply route-specific page typing** — entity detail pages emit the entity node; meta-pages emit `CollectionPage` with `about` → entity; static pages emit `AboutPage` / `WebPage`.
- **Assemble head / OG / Twitter tags** (already happens today in [`MetaTags.svelte`](frontend/src/lib/components/MetaTags.svelte) and [`./meta-tags.ts`](frontend/src/lib/components/meta-tags.ts)). Truncation, site-name suffix, canonical URL absolutization, OG-type bucket, Twitter-card decision — all presentation transforms with knowledge that lives frontend-side.
- **Maintain the External-IDs registry** as a small hand-edited TS constant (`{wikidata_id: "https://...", opdb_id: "https://...", ...}`). Stable, small.

**Two cross-cutting disciplines** apply to every JSON-LD emission, including the model-driven entity-page assembler:

- **`paths.base` discipline.** Every internal URL emitted into JSON-LD — entity `@id`s derived from `get_absolute_url()`, cross-reference `@id`s constructed from a referent's slug + relationship shape, `BreadcrumbList` items, `isPartOf` references — must be routed through `resolveHref()` before being concatenated with the origin, so a future `config.kit.paths.base` setting doesn't desynchronize JSON-LD URLs from rendered `<a>` hrefs. Reuse the `absolutize(pageUrl, path)` helper in [`jsonld.ts`](frontend/src/lib/components/jsonld.ts) — it already does this. Note that `pageUrl.pathname` already contains the base prefix, so callers using the current page's pathname should NOT route it back through `absolutize()`.
- **HTML-safe serialization.** All JSON-LD must be emitted through the [`JsonLd.svelte`](frontend/src/lib/components/JsonLd.svelte) component, which escapes `<`, `>`, `&` to `\uXXXX` so user-controlled content (entity descriptions, names) can't break out of the `<script>` tag. Never inline a raw `<script type="application/ld+json">` tag in a route — it bypasses the escape and exposes a content-injection hole. (Aside: Svelte treats literal `<script>` element children as opaque text and skips `{@html}` interpolation inside them, so the component emits the whole tag-payload-tag string via `{@html}` instead.)

#### Why frontend assembly

The declarations are presentation-only: schema.org type names, schema.org property names, OG type buckets — backend never uses them. Knowledge belongs where the consumer is. An alternative would be to declare them in Python and codegen to TS (parallel to `schema.d.ts`), but a hand-edited per-model TS file type-checked against `schema.d.ts` catches drift just as well without the codegen pipeline.

This applies to the _presentation vocabulary_ only. The _structural shape_ of the catalog — which fields are relations, what they target, FK vs M2M — is not presentation; it's a fact Django already owns and can derive from `_meta`. Per the model-driven principle ("derive from `_meta` whenever possible; declare only what Django can't express", [ModelDrivenMetadata.md](../model_driven_metadata/ModelDrivenMetadata.md)), that part _is_ codegen'd — see below.

#### Related-entity URLs from `catalog-meta.ts`

A cross-reference emits `{"@id": "<canonical URL of the referent>"}`. The referent ships as an `EntityRef` (`{name, slug}`), no `href` and no type tag. A `LinkableModel`'s canonical URL is `link_url_pattern` = `/{entity_type_plural}/{public_id}` — keyed on **`public_id`**, the uniform URL identity from [ModelDrivenLinkability.md](../model_driven_metadata/ModelDrivenLinkability.md), _not_ on `slug`. For most entities `public_id` is the slug; for `Location` it's `location_path` (route `/locations/[...path]`). To build the URL the assembler needs three facts about the target, all **derivable from the model** (`_meta` + `LinkableModel` ClassVars) and therefore codegen'd, not hand-declared:

- which entity type a given FK / M2M field targets — `field.related_model.entity_type`
- that entity type's URL prefix — `entity_type_plural`, already emitted
- which field on the ref carries the `public_id` value — `public_id_field` (`'slug'` for most, `'location_path'` for Location)

Both ride the existing `export_catalog_meta` → [`catalog-meta.ts`](frontend/src/lib/api/catalog-meta.ts) channel (today it ships `entity_type`, `entity_type_plural`, `label`, `label_plural` per entity). The per-entity record gains a nested `relationships` map so the whole shape stays cohesive — one object per entity, indexed `CATALOG_META[entityType].relationships[field]`:

```ts
export const CATALOG_META = {
  model: {
    entity_type: "model",
    entity_type_plural: "models",
    public_id_field: "slug", // 'location_path' for Location
    label: "Model",
    label_plural: "Models",
    relationships: {
      corporate_entity: { target_type: "corporate-entity", many: false },
      title: { target_type: "title", many: false },
      themes: { target_type: "theme", many: true },
    },
  },
  // ...
} as const;
```

Keys are snake_case to match the file's existing convention (`entity_type`, `entity_type_plural`), so the `Relationship` NamedTuple below (`target_type`, `many`) maps field-for-field with no re-casing in the emit step. `many` (from `field.many_to_many`) tells the assembler whether the API ships a single ref or a list. `target_type` names any **linkable** target — a catalog entity or another `LinkableModel` such as `user` (see [the linkable boundary](#linkable-crawlable-and-the-id-decision) below) — so it indexes straight back into `CATALOG_META` for the prefix. Canonical-URL construction is two cohesive lookups, no hand-declared prefixes or targets anywhere:

```ts
const rel = CATALOG_META[entityType].relationships[field]; // { target_type: 'corporate-entity', many: false }
const target = CATALOG_META[rel.target_type]; // { entity_type_plural: 'corporate-entities', public_id_field: 'slug', ... }
const publicId = ref[target.public_id_field]; // ref.slug — or ref.location_path for a Location target
const url = resolveHref(`/${target.entity_type_plural}/${publicId}`); // → absolutized into the @id
```

**The ref must carry the target's `public_id` value, and the bare `EntityRef` doesn't — because `public_id` only conquered half the system.** [ModelDrivenLinkability.md](../model_driven_metadata/ModelDrivenLinkability.md) migrated the system to `public_id` in **two layers, but only finished one:**

- **URL / route / lookup layer — fully `public_id`.** Every route is `{path:public_id}` and every lookup is `**{model.public_id_field: public_id}`. No `slug=` lookups remain in the catalog API.
- **Reference-_body_ layer — still `slug`.** The objects nested in a response to describe a referent were never migrated. The generic `EntityRef` is `{name, slug}` ([schemas.py:13-17](backend/apps/catalog/api/schemas.py#L13-L17)); ModelDrivenLinkability's only ref-related follow-up ("Rename JS-side `slug` parameter to `publicId`") renames JS _variables_ and explicitly keeps the wire value as `slug`.

It mostly doesn't bite because for slug-keyed entities `slug` **is** the `public_id` — so a `{name, slug}` ref's `slug` is the value the URL needs, by coincidence of equality. It breaks only for `Location`, whose `public_id` is `location_path ≠ slug`. The codebase already shows the ad-hoc workaround: Location-bearing FKs hand-roll richer ref schemas carrying `location_path` ([CorporateEntityLocationSchema:310-320](backend/apps/catalog/api/schemas.py#L310-L320) ships both `location_path` and `slug`; its ancestor rows [:300-307](backend/apps/catalog/api/schemas.py#L300-L307) keep `location_path` and drop `slug` precisely because that's the linkable identity). So **a forward relation targeting `Location` must serialize a `location_path`-bearing ref**, not a bare `EntityRef`, or the URL can't be built — the one case needing a ref-shape check during entity-page rollout.

**The clean fix that removes the carve-out entirely is finishing `public_id` into the body layer:** have refs expose `public_id` directly (`EntityRef` renames/adds `public_id`, populated from `obj.public_id`), so Layer 2 matches Layer 1. Then the assembler reads `ref.public_id` uniformly — no `public_id_field` indirection, no Location special case. This isn't tracked anywhere today (ModelDrivenLinkability's follow-up doesn't cover it), so it's a genuine prerequisite-or-workaround fork for the entity-page rollout: either finish the migration first, or special-case Location-targeting refs until it lands.

For `many: true` relations the assembler emits an array of `@id`s; the API must serialize the M2M in a deterministic order (an explicit `order_by` on the relation, not a bare `.all()`) so the emitted `@graph` is byte-stable across requests and stays cache-friendly.

Exporter change — extend the per-`cls` loop in [`export_catalog_meta`](backend/apps/catalog/management/commands/export_catalog_meta.py) with a `_meta` walk:

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

The per-entity entry also emits `public_id_field` straight from the `LinkableModel.public_id_field` ClassVar (`cls.public_id_field` — no walk needed; it's `'slug'` for every shipped model, `'location_path'` for Location). That's the field the assembler reads off the ref to get the `public_id` value for the URL.

**This `public_id_field` codegen belongs to the workaround path only.** It exists so the assembler can locate the `public_id` value inside a `slug`-shaped ref body (the two-layer wrinkle below). If we instead finish the `public_id` body-layer migration — refs expose `public_id` directly — then `public_id_field` becomes dead code: **drop it from the codegen and read `ref.public_id` uniformly.** Don't emit both. Resolve the fork (workaround vs. finish-the-migration) before implementing the exporter, not mid-way.

`not f.auto_created` is load-bearing: `get_fields()` also returns reverse accessors (e.g. `MachineModel.manufacturer` shows up on `Manufacturer` as a reverse FK), which satisfy `is_relation` + `related_model` and would bloat `relationships` with dozens of unused inverse entries. `f.concrete` is _not_ the right filter — `ManyToManyField` is non-concrete, so it would wrongly drop forward M2M like `themes`.

The target filter is **`LinkableModel`, not `CatalogModel`** — the property that matters for emitting an `@id` is "does this target have a canonical URL?", which is exactly what `LinkableModel` means. Widening the boundary captures cross-references to non-catalog-but-linkable entities (`user`, once it's a `LinkableModel` — see below) with zero special-casing: a `created_by → user` relation resolves through `CATALOG_META` like any other. Targets that aren't `LinkableModel` (internal FKs like `ingest_run`) are dropped — they have no URL, can't be an `@id`, and aren't valid `relationshipMap` targets. One consequence: `CATALOG_META`'s **entry set** must widen too, so a referenced non-catalog linkable model has an entry to resolve against — the exporter collects relationship targets and emits an entry for every referenced `LinkableModel`, not just `catalog_models()`. That spans apps (`user` lives in `accounts`), so `catalog-meta.ts` becomes a linkable-model registry and the name turns into a misnomer — `entity_types.py` already does the cross-app `LinkableModel` walk, so the precedent exists; rename TBD.

The filter is deliberately scoped to **forward relations the detail response serializes inline as `EntityRef`s** — not an oversight that omits reverse relations. The generic walk needs the referent's `public_id` to build a URL, and only serialized refs carry one; a reverse accessor `_meta` knows about but the Ninja schema doesn't ship would be a dead entry the assembler can never use. The one inverse relation v1 emits (`Title.workExample` → its Models) is handled by bespoke composition off the embedded `model_detail`, not this walk (see [Single-Model Titles](#single-model-titles)). When the hub-page [`ItemList` follow-up](#schemaorg-itemlist-on-hub-pages) lands and a detail response starts serializing its child set (e.g. `manufacturer.models`), the predicate widens to "forward FK/M2M **plus** reverse relations the response actually carries" — keyed off the response shape, since `_meta` alone can't tell which reverse accessors are exposed.

**Denormalized refs are not in `_meta`, and are deliberately not mapped.** A subtlety the `_meta` walk can't see: some refs on the response aren't the entity's own fields, they're _flattened from a related entity_. `ModelDetailSchema` exposes `manufacturer` (from `corporate_entity.manufacturer` — [machine_models.py:413](backend/apps/catalog/api/machine_models.py#L413)), `franchise` and `series` (from `title.franchise` / `title.series` — [:523-529](backend/apps/catalog/api/machine_models.py#L523-L529)). `MachineModel._meta` has `corporate_entity` and `title`, but **not** `manufacturer`/`franchise`/`series` — so `CATALOG_META.model.relationships` won't contain them. Mapping one in `relationshipMap` would resolve to no entry. That's correct: these are **UI display conveniences, redundant in the `@graph`.** The Model node already emits its direct FK (`corporate_entity → brand`, `title → exampleOfWork`); a consumer reaches the manufacturer by following `corporate_entity`'s `@id` to the CorporateEntity node, and franchise/series by following `title`'s. Emitting them on the Model node too would duplicate a one-hop-discoverable fact. So **`relationshipMap` maps only direct `_meta`-backed fields; flattened convenience refs are omitted** (and an implementer should not try to map `manufacturer`/`franchise`/`series` on `model`). If a specific flattened ref ever genuinely must appear on a node, that one key takes an explicit `{ property, target }` declaration in the per-model file — the escape hatch, used only where transitive discovery isn't enough.

This is the lightest model-driven pattern — a pure `_meta` walk — and a parity test pins the emitted shape (per the codegen rules in [ModelDrivenMetadata.md](../model_driven_metadata/ModelDrivenMetadata.md)). It does **not** revive the deferred [`CatalogRelationshipSpec`](../model_driven_metadata/ModelDrivenCatalogRelationshipMetadata.md): that spec carries claim-resolution metadata (namespace, `identity_fields`, subject) the structured-data layer never reads, and its revival trigger is a second consumer of _that_ metadata. Cross-references consume only FK _targets_, which `_meta` already knows. With this in place, `catalog-meta.ts` becomes the model→frontend relationship-shape source; future generic consumers (forms, tables, relationship traversal) read it rather than adding a parallel registry — worth a line in the exporter docstring so the next person doesn't.

#### Linkable, crawlable, and the `@id` decision

Two orthogonal properties decide how a cross-reference is emitted, and they have **different sources** — neither lives in the per-model TS file:

- **Linkable** — the target has a canonical URL. This is a model fact: `issubclass(LinkableModel)`, surfaced by whether the target has a `CATALOG_META` entry at all (the walk above only emits relations to linkable targets, so _inclusion encodes linkability_ — no separate `linkable` boolean is needed).
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

**Cross-references are an `@id` or nothing; v1 never emits a name-only blank node here.** A useful blank node would carry the referent's `@type` (`{"@type": "Brand", "name": "Stern"}`), but that type lives in the _referent's_ `schemaOrg.types` — neither `relationshipMap` (property name only) nor `CATALOG_META` (no schema.org types) has it, so a typed blank node would mean cross-loading the referent's `ModelFrontendInfo` via the `index.ts` aggregator. v1 has no case that needs it (catalog targets are crawlable → `@id`; `user` is omitted pre-SSR), so the generic walk emits `@id` or omits, full stop, and the cross-load is deferred until a concrete case demands it. (The page-scoped blank nodes elsewhere — team members on `/about/people` — are a different path: the _page_ knows the type and composes them directly, no cross-load.)

**Why a declared relation can't fail to resolve.** The hazard this forecloses: a `relationshipMap` entry whose target has no `CATALOG_META` entry, leaving the assembler to read `relationships[field]` as `undefined` and crash at render. The `LinkableModel` boundary plus the widened entry set removes it structurally — every linkable target has an entry, so any relation the assembler is asked to emit resolves. The one remaining mistake worth a light guard is a `relationshipMap` key that names a _scalar_ field rather than a relation; that's a different, rarer error and a small assertion covers it.

**`user` is the worked example of the split, and is currently mis-declared.** It is linkable in truth — `/users/[username]` exists — but `User(AbstractUser)` is _not_ a `LinkableModel` ([accounts/models.py](backend/apps/accounts/models.py)), and its detail route sits in `SEARCH_ENGINE_NON_INDEXABLE_ROUTE_IDS` (CSR, not crawlable). So today a `created_by → user` reference can't be emitted at all (no entry). Once `User` is promoted to `LinkableModel` the reference becomes emittable as an `@id` (linkable ✓, crawlable ✗ → the assembler may emit the `@id` or omit per the table) — never a blank node, per the rule above. **Prerequisite for any User cross-reference: promote `User` to `LinkableModel`** — which also dovetails with the sitemap's existing "User would need to be a `LinkableModel`" note. Until then, User refs are simply absent.

#### API response audit

The frontend assembler needs raw values, not presentation-shaped ones. Audit findings (2026-05):

- **Description:** ✅ ships as `RichTextSchema` with four slots — `.text` (authoring markdown, including `[[type:slug]]` reference tokens), `.html` (rendered, tokens resolved to `<a>` tags), `.plain` (backend-flattened prose with tokens resolved and markdown/HTML stripped), and `.citations`. The frontend should use `.plain` for `<meta name="description">`, `og:description`, JSON-LD `description`, and other machine-readable text consumers. Display-limited surfaces still truncate frontend-side per consumer; JSON-LD uses `.plain` untruncated.
- **Image:** ✅ `hero_image_url` is a constructed absolute URL string (`build_public_url(build_storage_key(...))`) — raw enough for the v1 commitment to emit the `display` rendition uniformly.
- **External IDs:** ✅ raw scalars (`ipdb_id: int`, `opdb_id: str`, `pinside_id`, `fandom_page_id`), not formatted strings — **except** `wikidata_id`, explicitly omitted from `PersonDetailSchema`. Shipping it is a one-field widening, required before Person JSON-LD can emit a Wikidata `sameAs`.
- **FK / M2M references:** ship as `EntityRef` (`{name, slug}`) — **no `href`, no type tag**. `EntityRef` is shared infrastructure (hundreds of call sites); widening it is out of scope. The referent's canonical URL is instead constructed frontend-side from the slug plus the codegen'd relationship shape — see [Related-entity URLs](#related-entity-urls-from-catalog-metats).

Completed response-widening for the taxonomy tranche: the backend-owned `description.plain` projection.

Remaining response/codegen prerequisites for richer entity pages: `wikidata_id` on `PersonDetailSchema` (one field) and the relationship-shape codegen above. Nothing structural beyond the unresolved `public_id` body-layer fork.

### Per-model frontend info

Each Django model has a companion TypeScript file at `frontend/src/lib/models/<model-name>.ts` carrying presentation declarations the backend doesn't need to know about — what schema.org type to emit, which fields map to which schema.org properties, etc. This is per the principle that **per-model declarations live where the consumer lives**: backend-relevant knowledge in Django models, presentation-only knowledge in TS.

A Django model's full definition therefore spans two files: the Django class (persistence, validation, URLs, claim machinery) and its companion TS file (schema.org info, and future buckets for any other purely-presentation per-model concern). See [ModelDrivenMetadata.md](docs/plans/model_driven_metadata/ModelDrivenMetadata.md) for the broader principle.

✅ DONE for the taxonomy tranche: `frontend/src/lib/models/types.ts`, `frontend/src/lib/models/schema-org.ts`, the 11 taxonomy per-model files and `index.ts` exist. The current assembler intentionally supports only the no-relation entity shape needed by these pages: `schemaOrg.types`, canonical `@id`, `name` and untruncated `description.plain`.

**Key naming:** `fieldMap` and `relationshipMap` keys are the entity field names as they appear on the API response — which is the project's snake_case (Django Ninja schemas don't rename fields). `release_year`, not `releaseYear`. Type-checked via `Partial<Record<keyof TSchema, string>>` against the codegen'd schema, so a serializer convention change (or a renamed Django field) breaks the per-model TS file at compile.

**Shared interfaces** (one place for all per-model files to conform to):

```ts
// frontend/src/lib/models/types.ts
import type { CatalogEntityKey } from "$lib/api/catalog-meta";

export interface SchemaOrgInfo<TSchema> {
  types: readonly string[] | ((entity: TSchema) => readonly string[]);
  fieldMap?: Partial<Record<keyof TSchema, string>>;
  relationshipMap?: Partial<Record<keyof TSchema, string>>;
}

export interface ModelFrontendInfo<TSchema> {
  // The canonical CATALOG_META key for this entity — its `entity_type`
  // ('model', 'title', 'corporate-entity', …). This is the ONE key the
  // assembler uses to index CATALOG_META; never the camelCase export name.
  entityType: CatalogEntityKey;
  schemaOrg: SchemaOrgInfo<TSchema>;
  // future buckets sit alongside `schemaOrg` as optional fields:
  // openGraph?: OpenGraphInfo<TSchema>;
  // displayCopy?: DisplayCopyInfo<TSchema>;
  // adminAffordances?: AdminAffordancesInfo<TSchema>;
}
```

**Three names, one canonical key.** A model has three distinct identifiers in play: its `entity_type` (`'model'`), its file/export name (`machine-model.ts` → `machineModel`), and — historically — whatever string got passed to `buildSchemaOrgNode`. These must not be conflated: the assembler indexes `CATALOG_META` and resolves `target_type`s using **`entityType` (the `entity_type` value) exclusively**. The export name is just a JS binding; `buildSchemaOrgNode` receives the info _object_, reads `info.entityType`, and never sees a bare string. `CatalogEntityKey` (already exported from `catalog-meta.ts`) constrains `entityType` to a real key, so a typo or a stale value fails at compile.

**Per-model file:**

```ts
// frontend/src/lib/models/machine-model.ts
import type { MachineModelDetailSchema } from "$lib/api/schema";
import type { ModelFrontendInfo } from "./types";

export const machineModel: ModelFrontendInfo<MachineModelDetailSchema> = {
  entityType: "model", // the CATALOG_META key, NOT "machineModel"
  schemaOrg: {
    types: ["Game", "ProductModel"],
    fieldMap: { release_year: "releaseDate" },
    relationshipMap: {
      corporate_entity: "brand",
      title: "exampleOfWork",
    },
  },
};
```

**Location's per-row schemaOrg.types — same shape, function instead of array:**

```ts
// frontend/src/lib/models/location.ts
import type { LocationDetailSchema } from "$lib/api/schema";
import type { ModelFrontendInfo } from "./types";

export const location: ModelFrontendInfo<LocationDetailSchema> = {
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
        case "":
          return ["Place"];
        default:
          return ["AdministrativeArea"];
      }
    },
    fieldMap: { short_name: "alternateName" },
  },
};
```

No asymmetry vs other models — `schemaOrg.types` just accepts either form. The function's parameter is typed as `LocationDetailSchema` via the `ModelFrontendInfo<LocationDetailSchema>` generic; no extra annotation needed inside the function.

**Type checking and drift detection:**

- The `: ModelFrontendInfo<TSchema>` annotation type-checks the whole entry against the contract.
- `Partial<Record<keyof TSchema, string>>` on `fieldMap` and `relationshipMap` requires keys to be actual fields of the API schema. A renamed Django field invalidates the per-model TS file after `make codegen` regenerates `schema.d.ts` — TS compile fails until the file is updated. Drift caught at build time without custom validation.

**File layout:**

```text
frontend/src/lib/models/
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

✅ DONE files from the taxonomy tranche: `theme.ts`, `gameplay-feature.ts`, `technology-generation.ts`, `technology-subgeneration.ts`, `display-type.ts`, `display-subtype.ts`, `cabinet.ts`, `game-format.ts`, `reward-type.ts`, `tag.ts`, `credit-role.ts`, plus the shared files listed above. The non-taxonomy files in this layout remain future work.

**Consumer access:** route layouts import their specific model directly. A generic consumer (rare today) can use the `index.ts` aggregator for lookup by `entity_type`.

#### Value transformations

Field values shipped raw from the backend often need shape-shifting before they're emitted under a schema.org property. The transforms live in the frontend's `buildSchemaOrgNode` (or per-bucket assembler) and dispatch on the **target schema.org property name**, not on the source Django field type:

- Target is a date-shaped property (`releaseDate`, `birthDate`, `deathDate`, `foundingDate`, etc.) — coerce the source value to a partial ISO 8601 string. For year-only integers (`release_year` is `PositiveIntegerField`, not `DateField`), that's `String(year)` — schema.org accepts `"1992"` as a valid partial `releaseDate`. For full date values, the API already serializes ISO 8601.
- Target is a numeric property (`aggregateRating`, etc.) — already shipped as a number from the backend.
- Target is a text property sourced from rich text — use the backend's plain projection (`RichTextSchema.plain`). Do not reconstruct prose with a frontend markdown stripper; if a future MarkdownField needs structured-data text, expose the same backend-owned plain projection first.

The target-property-aware dispatch matters because the source type alone can't determine the right coercion: an integer field could be a year, a count, or an external ID, and the target property tells the assembler which shape to emit.

**`relationshipMap` is walked separately:** for each declared FK / M2M attribute, the assembler reads the referenced `EntityRef` (`{name, slug}`) from the API response — a single object for an FK, an array when the relationship shape says `many: true` — constructs the referent's canonical URL from its slug and the codegen'd relationship shape (see [Related-entity URLs](#related-entity-urls-from-catalog-metats)), and emits `{"@id": "https://flipcommons.org/..."}` under the declared schema.org property. Unlike `fieldMap`, this doesn't go through value transforms — the relationship value is always an `@id` reference, never a scalar.

✅ DONE — glossary entities (`Theme`, `GameplayFeature`, all taxonomy classes) don't need any field-mapped properties — name and description are everything schema.org wants from them. Their per-model TS files omit `fieldMap` and `relationshipMap`.

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
      ...title-tier fields (name, abbreviations, franchise, series; sameAs for Title's external IDs)
    },
    {
      "@type": ["Game", "ProductModel"],
      "@id": "https://flipcommons.org/models/doctor-who",
      "exampleOfWork": {"@id": "https://flipcommons.org/titles/doctor-who"},
      "name": "Doctor Who",
      ...model-tier fields (description, manufacturer, releaseDate, gameplay/technology cross-references; sameAs for Model's external IDs)
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
import { title, machineModel } from "$lib/models";

const graph = [buildSchemaOrgNode(data, title)];
if (data.model_detail) {
  graph.push(buildSchemaOrgNode(data.model_detail, machineModel));
}
graph.push(buildBreadcrumbList(crumbs));
```

The second arg is the per-model info _object_ (`title`, `machineModel`), not a string. `buildSchemaOrgNode` reads `info.entityType` (`'title'`, `'model'`) to index `CATALOG_META` — so the camelCase export name `machineModel` never has to match the `entity_type` `'model'`.

The trigger condition (`data.model_detail` populated) already exists — `TitleDetailSchema.model_detail` is populated inline only for single-Model Titles, per SingleModelTitles.md. The frontend's rule is "if the API embedded the Model, assemble its node too." Same `buildSchemaOrgNode()` machinery as any other entity — no special path.

## Types of pages

### Entity detail pages

Such as `/titles/[slug]`, `/models/[slug]`, `/people/[slug]` etc.

Target shape for every SSR entity detail page: each page emits two top-level nodes in `@graph`:

- The entity itself as a typed node (`Game`, `Person`, `Organization`, etc.) with `@id` cross-references to related entities and `sameAs` links to external IDs. No `WebPage` wrapper — the type is the thing, not the medium.
- A `BreadcrumbList` node carrying the page's hierarchical trail. Google's BreadcrumbList rich result replaces the URL in SERPs with a readable trail, measurably lifting click-through. Example chains: Title page → `Home › Godzilla`; Model page → `Home › Godzilla › Godzilla Pro` (Model's parent is its Title; there's no `/models` listing page, and we skip `/titles` since it's CSR-only and an empty shell to crawlers). The JSON-LD chain is richer than the visible UI breadcrumb — that's allowed by Google's policies as long as every item in the chain is a real, accessible page reflecting the site's genuine hierarchy.

✅ DONE for taxonomy detail pages: Theme, GameplayFeature, TechnologyGeneration, TechnologySubgeneration, DisplayType, DisplaySubtype, Cabinet, GameFormat, RewardType, Tag and CreditRole now emit the entity node plus a `Home › {name}` `BreadcrumbList`. These no-relation pages intentionally omit cross-references, images and `sameAs` until the richer entity-page tranche widens the assembler.

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
