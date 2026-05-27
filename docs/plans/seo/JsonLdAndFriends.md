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

### Open Graph

Open Graph (OG) is de facto link-preview standard: Facebook, LinkedIn, iMessage, Slack, Discord, Bluesky, Mastodon (and Twitter as a fallback) all read OG.

It uses `<meta property="og:*">` tags in `<head>`. Small fixed property set per page — `og:type`, `og:title`, `og:description`, `og:image`, `og:url`, `og:site_name`. `og:type` draws from a small vocabulary (`article`, `profile`, `website`, etc.).

This project emits `og:type`, `og:site_name`, `og:title`, `og:description`, `og:url`, `og:image` and `og:image:alt`, but there are gaps to close:

- Every page hardcodes `og:type` to `website`; some pages like a Person page should be other things, like `profile`.
- `og:image:alt` is built per-layout as `` `${entity.name} pinball machine` `` — wrong for Person, Manufacturer, CorporateEntity (a designer is not a pinball machine)
- Same six layouts as the head info; listing pages emit nothing

### Twitter card

`<meta name="twitter:*">` tags that Twitter uses to control previews on its site.

This project currently emits `twitter:card`, `twitter:title`, `twitter:description`, `twitter:image` and `twitter:image:alt`; see [`MetaTags.svelte`](frontend/src/lib/components/MetaTags.svelte).

However, Twitter cascades from OG when Twitter-specific tags are absent, so the only one worth emitting is `twitter:card`. The title/description/image trio are redundant (OG cascade covers them) and should be removed.

The current `twitter:card` selects between `summary` (small icon preview) and `summary_large_image` (hero card preview) based on whether the entity has a promotable image — the `twitterCardType()` function keys off image presence, which matches the target behavior. Post-refactor the image source becomes [`MediaSupportedModel.primary_image`](#mediasupportedmodel) (present → `summary_large_image`, absent or for non-MediaSupported entities → `summary`); selection logic itself is unchanged.

### JSON-LD

A JSON document inside `<script type="application/ld+json">` in `<head>`, using vocabularies from [schema.org](https://schema.org). Consumed by search engines for rich results and knowledge panels, by LLM crawlers for citation accuracy and by other databases linking in via `sameAs`. Each page emits a `@graph` of one or more typed nodes (`Game`, `Person`, `Organization`, etc.) with `@id` cross-references to related entities and `sameAs` to external IDs. The highest-fidelity representation — arbitrarily rich, nested and addressable.

This project does not yet include any JSON-LD info.

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

We deliberately don't use `product` (Facebook's extension) for MachineModel — it's commerce-oriented (price, availability, SKU) and we're not selling machines.

## Architecture

### Autogenerated representations

We will automatically generate these different machine-readable representations based on information in the Django models, as per [ModelDrivenMetadata.md](docs/plans/model_driven_metadata/ModelDrivenMetadata.md).

The same facts feed all of these machine-readable representations. 90% of this information is already well-described by the model and won't require additional per-model mapping information.

#### Information sources

Some come from the Django model (backend), some from the per-model TS file ([see below](#per-model-frontend-info)):

- **Canonical URL** — `LinkableModel.get_absolute_url()` (backend; already in API responses)
- **Display name** — `LinkableModel.name` (backend)
- **Description** — [`DescribedModel`](#describedmodel)`.description`, raw markdown shipped from backend; frontend strips and truncates per consumer. Truncation lengths: `<meta name="description">` ~155 chars (Google SERP display limit), `og:description` ~200 chars (Facebook/LinkedIn preview cards), `twitter:description` ~200 chars (when emitted; usually cascades from OG). JSON-LD `description` is **not truncated** — machine-readable consumers (LLMs, search engines, linked-data crawlers) benefit from the full text and have no display constraint.
- **Primary image** — [`MediaSupportedModel`](#mediasupportedmodel)`.primary_image`: primary image of primary category. Emitted as the `display` rendition's absolute URL via `build_public_url(build_storage_key(asset.uuid, "display"))` on the backend; shipped as a URL string on the API response. Same URL used across JSON-LD `image`, OG `og:image`, Twitter `twitter:image` and sitemap `<image:loc>`. Aspect-ratio crops per consumer are a [Bunny-Optimizer follow-up](#bunny-optimizer-driven-aspect-ratio-crops); v1 uses one rendition for all.

  **Deliberate exception to "presentation lives frontend-side":** the choice of which rendition to emit (`display` vs `thumb` vs `original`) is a presentation decision, but it's encoded in the Python `build_public_url(... "display")` call rather than in TS. The CDN base URL (`MEDIA_PUBLIC_BASE_URL`) is server-side config that isn't (and shouldn't be) exposed to the frontend, so URL construction has to happen backend. We could ship the asset's UUID + rendition_type and have TS build the URL — but that means duplicating the base URL into frontend env, and the storage layer's URL conventions naturally belong with the storage layer. Net: one small backend presentational decision (rendition selection), justified by where the URL construction primitive lives.

- **Last modified** — `TimeStampedModel.updated_at` (backend)
- **Schema.org types** — declared in the per-model TS file's `schemaOrg.types` field. Static array for most entities; per-row function for Location. See [Per-model frontend info](#per-model-frontend-info).
- **Cross-references** — declared in the per-model TS file's `schemaOrg.relationshipMap`. Each declared FK / M2M attribute carries its schema.org property name (`corporate_entity → brand`, `title → exampleOfWork`, `themes → genre`, etc.). The frontend metadata builder walks the declared set and emits an `@id` reference to the referent's canonical URL under the declared property. Undeclared relationships are not emitted.
- **External-system identity** — small hand-edited TS constant mapping specific field names (`wikidata_id`, `opdb_id`, `ipdb_id`, `opdb_manufacturer_id`, `ipdb_manufacturer_id`) to URL templates. Field-name-based, not prefix-based — `ipdb_rating` is a number stored on our model, not an ID, and won't accidentally match. Each present, non-null field becomes a `sameAs` entry.

### Backend vs frontend responsibilities

All metadata assembly — JSON-LD, head, OG, Twitter — lives in the frontend. Backend ships raw entity facts; the frontend reads them plus per-model declarations from [`frontend/src/lib/models/`](#per-model-frontend-info) and emits the metadata.

#### Backend's job

Serve raw entity facts on the entity detail API response: `name`, `description` (raw markdown), `hero_image_url` (the `display` rendition's absolute URL), `updated_at` (ISO 8601), FK references with their canonical hrefs, external-ID scalars (`ipdb_id`, `opdb_id`, `wikidata_id`, etc.). Mostly what's already shipped today; see [API response audit](#api-response-audit) below.

#### Frontend's job

- **Hold per-model presentation declarations** in [`frontend/src/lib/models/<model-name>.ts`](#per-model-frontend-info) — one file per Django model, containing the schema.org types, field map, relationship map, and any other purely-presentation per-model info.
- **Assemble the SchemaOrgNode** for each entity via a generic `buildSchemaOrgNode(entity, modelInfo)` function that walks the declarations against the entity facts. ~50-80 lines of TS.
- **Compose the `@graph`** per page — pick which nodes go in (entity node always; Model node for single-Model Titles when `data.model_detail` is present; `BreadcrumbList`; `CollectionPage` for meta-pages).
- **Apply route-specific page typing** — entity detail pages emit the entity node; meta-pages emit `CollectionPage` with `about` → entity; static pages emit `AboutPage` / `WebPage`.
- **Assemble head / OG / Twitter tags** (already happens today in [`MetaTags.svelte`](frontend/src/lib/components/MetaTags.svelte) and [`./meta-tags.ts`](frontend/src/lib/components/meta-tags.ts)). Truncation, site-name suffix, canonical URL absolutization, OG-type bucket, Twitter-card decision — all presentation transforms with knowledge that lives frontend-side.
- **Maintain the External-IDs registry** as a small hand-edited TS constant (`{wikidata_id: "https://...", opdb_id: "https://...", ...}`). Stable, small.

#### Why frontend assembly

The declarations are presentation-only: schema.org type names, schema.org property names, OG type buckets — backend never uses them. Knowledge belongs where the consumer is. An alternative would be to declare them in Python and codegen to TS (parallel to `schema.d.ts`), but a hand-edited per-model TS file type-checked against `schema.d.ts` catches drift just as well without the codegen pipeline.

#### API response audit

The frontend assembler needs raw values, not presentation-shaped ones. Audit needed:

- **Description:** does the current entity detail response carry raw markdown, or is it pre-stripped/rendered? If pre-shaped, expose a raw markdown field alongside (frontend strips itself).
- **Image:** today's API ships `hero_image_url` as a constructed absolute URL string — already raw enough for the v1 commitment to emit the `display` rendition uniformly.
- **External IDs:** likely already raw scalars (`ipdb_id: 4032`). Verify they're not formatted strings.
- **FK references:** likely already shipped with canonical `href`. Verify.

The audit may produce small response-widening commits as part of v1 implementation; nothing structural.

### Per-model frontend info

Each Django model has a companion TypeScript file at `frontend/src/lib/models/<model-name>.ts` carrying presentation declarations the backend doesn't need to know about — what schema.org type to emit, which fields map to which schema.org properties, etc. This is per the principle that **per-model declarations live where the consumer lives**: backend-relevant knowledge in Django models, presentation-only knowledge in TS.

A Django model's full definition therefore spans two files: the Django class (persistence, validation, URLs, claim machinery) and its companion TS file (schema.org info, and future buckets for any other purely-presentation per-model concern). See [ModelDrivenMetadata.md](docs/plans/model_driven_metadata/ModelDrivenMetadata.md) for the broader principle.

**Key naming:** `fieldMap` and `relationshipMap` keys are the entity field names as they appear on the API response — which is the project's snake_case (Django Ninja schemas don't rename fields). `release_year`, not `releaseYear`. Type-checked via `Partial<Record<keyof TSchema, string>>` against the codegen'd schema, so a serializer convention change (or a renamed Django field) breaks the per-model TS file at compile.

**Shared interfaces** (one place for all per-model files to conform to):

```ts
// frontend/src/lib/models/types.ts
export interface SchemaOrgInfo<TSchema> {
  types: readonly string[] | ((entity: TSchema) => readonly string[]);
  fieldMap?: Partial<Record<keyof TSchema, string>>;
  relationshipMap?: Partial<Record<keyof TSchema, string>>;
}

export interface ModelFrontendInfo<TSchema> {
  schemaOrg: SchemaOrgInfo<TSchema>;
  // future buckets sit alongside `schemaOrg` as optional fields:
  // openGraph?: OpenGraphInfo<TSchema>;
  // displayCopy?: DisplayCopyInfo<TSchema>;
  // adminAffordances?: AdminAffordancesInfo<TSchema>;
}
```

**Per-model file:**

```ts
// frontend/src/lib/models/machine-model.ts
import type { MachineModelDetailSchema } from "$lib/api/schema";
import type { ModelFrontendInfo } from "./types";

export const machineModel: ModelFrontendInfo<MachineModelDetailSchema> = {
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
- `Partial<Record<keyof TSchema, string>>` on `fieldMap` and `relationshipMap` requires keys to be actual fields of the API schema. A renamed Django field invalidates the per-model TS file after `make api-gen` regenerates `schema.d.ts` — TS compile fails until the file is updated. Drift caught at build time without custom validation.

**File layout:**

```text
frontend/src/lib/models/
├── types.ts            (shared interfaces)
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

**Consumer access:** route layouts import their specific model directly. A generic consumer (rare today) can use the `index.ts` aggregator for lookup by `entity_type`.

#### Value transformations

Field values shipped raw from the backend often need shape-shifting before they're emitted under a schema.org property. The transforms live in the frontend's `buildSchemaOrgNode` (or per-bucket assembler) and dispatch on the **target schema.org property name**, not on the source Django field type:

- Target is a date-shaped property (`releaseDate`, `birthDate`, `deathDate`, `foundingDate`, etc.) — coerce the source value to a partial ISO 8601 string. For year-only integers (`release_year` is `PositiveIntegerField`, not `DateField`), that's `String(year)` — schema.org accepts `"1992"` as a valid partial `releaseDate`. For full date values, the API already serializes ISO 8601.
- Target is a numeric property (`aggregateRating`, etc.) — already shipped as a number from the backend.
- Target is a text property sourced from a `MarkdownField` — the frontend strips markdown (using the parser it already ships for rendering).

The target-property-aware dispatch matters because the source type alone can't determine the right coercion: an integer field could be a year, a count, or an external ID, and the target property tells the assembler which shape to emit.

**`relationshipMap` is walked separately:** for each declared FK / M2M attribute, the assembler reads the referenced entity's canonical `href` from the API response (FK fields are shipped as `{href, name, ...}` objects, or arrays of them for M2M), absolutizes the URL if needed, and emits `{"@id": "https://flipcommons.org/..."}` under the declared schema.org property. Unlike `fieldMap`, this doesn't go through value transforms — the relationship value is always an `@id` reference, never a scalar.

Glossary entities (`Theme`, `GameplayFeature`, all taxonomy classes) don't need any field-mapped properties — name and description are everything schema.org wants from them. Their per-model TS file has an empty (or absent) `fieldMap`.

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
const graph = [buildSchemaOrgNode(data, "title")];
if (data.model_detail) {
  graph.push(buildSchemaOrgNode(data.model_detail, "machineModel"));
}
graph.push(buildBreadcrumbList(crumbs));
```

The trigger condition (`data.model_detail` populated) already exists — `TitleDetailSchema.model_detail` is populated inline only for single-Model Titles, per SingleModelTitles.md. The frontend's rule is "if the API embedded the Model, assemble its node too." Same `buildSchemaOrgNode()` machinery as any other entity — no special path.

## Types of pages

### Entity detail pages

Such as `/titles/[slug]`, `/models/[slug]`, `/people/[slug]` etc.

Each page emits two top-level nodes in `@graph`:

- The entity itself as a typed node (`Game`, `Person`, `Organization`, etc.) with `@id` cross-references to related entities and `sameAs` links to external IDs. No `WebPage` wrapper — the type is the thing, not the medium.
- A `BreadcrumbList` node carrying the page's hierarchical trail. Google's BreadcrumbList rich result replaces the URL in SERPs with a readable trail, measurably lifting click-through. Example chains: Title page → `Home › Godzilla`; Model page → `Home › Godzilla › Godzilla Pro` (Model's parent is its Title; there's no `/models` listing page, and we skip `/titles` since it's CSR-only and an empty shell to crawlers). The JSON-LD chain is richer than the visible UI breadcrumb — that's allowed by Google's policies as long as every item in the chain is a real, accessible page reflecting the site's genuine hierarchy.

### Entity meta-pages

Every catalog entity has `/[entity]/[slug]/edit-history` and `/[entity]/[slug]/sources`.

Each will emit a `CollectionPage` typed node with `about` → the entity's `@id`. The page is about the entity but its primary content is the collection (of ChangeSets / sources), so `CollectionPage` is more precise than plain `WebPage`, and `about` is more accurate than `mainEntity` (the entity isn't the page's primary subject; the collection is).

For single-Model Titles, the Model's `/models/[slug]/edit-history` and `/models/[slug]/sources` remain accessible even though `/models/[slug]` itself redirects (per SingleModelTitles.md). Each meta-page points `about` at its own entity's `@id`: `/titles/[slug]/edit-history` is about the Title (`@id: /titles/[slug]`), `/models/[slug]/edit-history` is about the Model (`@id: /models/[slug]`). Each entity retains its identity regardless of collapse status (see [Single-Model Titles](#single-model-titles)), so meta-pages have unambiguous about-targets — no collision between Title-side and Model-side history pages.

These pages emit the same `BreadcrumbList` node pattern as entity detail pages, with the trail extended one level (`Home › Godzilla › Godzilla Pro › Edit history`).

### Static pages

Static pages use the same `<head>` / OG / Twitter primitive as entity pages, but with hand-authored values. No model derivation because there's no model. Each page also emits a `BreadcrumbList` node.

#### /

The home page emits site-level metadata, such as a `WebSite` node with a `SearchAction` describing the site's search endpoint, which Google uses to render the sitelinks search box in SERPs. Hand-authored, one-off.

No `BreadcrumbList` — the home page is the root; a breadcrumb of `Home` pointing at itself adds nothing.

#### /about

Schema.org `@type`: `AboutPage` (a `WebPage` subtype) so Google understands it's the site's about page.

`BreadcrumbList`: `Home › About`.

Body content is hand-authored prose; no additional JSON-LD nodes.

#### /about/people

Schema.org `@type`: `CollectionPage` — the page presents a collection (team members). `AboutPage` is already taken by `/about` itself; `ProfilePage` would be wrong (that's for a single person, and this page has two).

`BreadcrumbList`: `Home › About › People`.

Body: one `Person` node per team member, emitted as blank nodes (no `@id`) — same rationale as `BreadcrumbList`: page-scoped, never referenced from anywhere else. Each carries `name`, `description`, `image`, `homeLocation` (and `sameAs` for any external profiles linked from the bio). If we later emit a FlipCommons `Organization` node (likely on the home page), each Person can include a `worksFor` or be referenced from the Organization's `founder` property to make the founding relationship machine-readable.

If/when team members get FlipCommons User accounts and User pages go SSR, the User's canonical URL becomes their `@id`; the blank-node interim is just a stopgap.

#### /privacy

Schema.org `@type`: plain `WebPage` (no specific subtype fits).

`BreadcrumbList`: `Home › Privacy`. Treated as a top-level peer of About, not a child — the legal pages live under SvelteKit's `(legal)` layout group, not under `/about`.

Body content is hand-authored prose; no additional JSON-LD nodes.

The same shape applies to `/terms` and `/licensing` — plain `WebPage`, `BreadcrumbList[Home, [page name]]`, no body nodes. Listed as separate subsections if you want each to have its own anchor.

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

### DescribedModel

Doesn't exist yet.

```python
class DescribedModel(models.Model):
    """Abstract base for entities with a long-form markdown description."""

    description = MarkdownField(blank=True)

    class Meta:
        abstract = True
```

`CatalogModel` will declare it in its base list:

```python
class CatalogModel(
    LinkableModel,
    LifecycleStatusModel,
    ClaimControlledModel,
    DescribedModel,
):
    ...
```

This will delete the redundant `description = MarkdownField(blank=True)` lines across the 20 catalog entities.

### MediaSupportedModel

Exists at [apps/media/models/base.py](backend/apps/media/models/base.py), with `MEDIA_CATEGORIES` already declared per subclass. Needs a `primary_category` ClassVar and a `primary_image` resolver.

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

Each concrete subclass declares its `primary_category`, such as:

- `Title`, `MachineModel` → `"backglass"`
- `Manufacturer`, `CorporateEntity` → `"logo"`

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
