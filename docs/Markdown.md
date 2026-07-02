# Markdown

The catalog stores long-form prose as **markdown**. Every catalog `DescribedModel.description` is a markdown field, and it is claim-controlled like any other field — the stored value is a claim, materialized by resolution. The markdown subsystem does three jobs: it renders markdown to safe HTML and plain text, it resolves inline `[[type:id]]` **wikilinks** to live records, and it maintains a **reference graph** ("what links here") by indexing those links into a shared table.

The code lives in `backend/apps/core/markdown/` (render, field conversion, the reference bridge) and `backend/apps/core/wikilinks/` (the link-type registry). The shared graph model is `backend/apps/core/models/references.py`.

## Lifecycle

A wikilink flows authoring → storage → graph → HTML. The conversion happens at claim write, but the reference sync happens later, at **resolution**:

```text
Author types  [[type:public-id]]              ← [[ opens the wikilink picker/autocomplete
      │  prepare_markdown_claim_value → convert_authoring_to_storage
      │  (claim write; validates every target exists, else ValidationError)
      ▼
Claim value stored as  [[type:id:pk]]         ← the DB always holds the pk form
      │  resolution picks the winning claim and materializes it onto the entity
      ▼
sync_references(entity, value)                ← per markdown field; (re)writes RecordReference edges
      │
      ▼
render_markdown_html                          ← [[type:id:pk]] → links / footnotes, then sanitized HTML
```

## Wikilinks: `[[type:id]]`

Inline links use a `[[type:ref]]` marker — `[[manufacturer:williams]]`, `[[title:medieval-madness]]`, `[[cite:bcdfghjk]]`. Contributors insert them by typing `[[`, which opens the wikilink picker and autocomplete. Each marker has **two representations**:

- **Authoring** — `[[type:public-id]]` — what the editor shows and the contributor types. The `public-id` is an editorial handle (a slug, a `location_path`, a citation slug).
- **Storage** — `[[type:id:pk]]` — what the database stores. The `pk` is the target's primary key.

The split exists because public-ids are mutable (a slug can be re-curated) but primary keys are stable. Storing the **pk** means a link survives a rename of its target; showing the **public-id** means authors read and write a stable, human-meaningful handle. The DB always holds storage form; the editor always sees authoring form.

On a claim write, `prepare_markdown_claim_value` (`apps/core/markdown/field.py`) is the single integration point that runs `convert_authoring_to_storage` for every markdown field: it finds every authoring marker, batch-resolves the public-ids to pks and rewrites the markers — raising `ValidationError` if any target does not exist, so a save can't persist a dangling link. `convert_storage_to_authoring` (and the batched `resolve_wikilink_authoring`) does the reverse for editing and history views. These live in `apps/core/markdown/field.py`. Types whose `public_id_field` is `None` are **id-based** — their marker is `[[type:pk]]` in both forms and needs no conversion.

### The link-type registry

Each link type is a frozen `LinkType` (`apps/core/wikilinks/types.py`) declaring its `name`, `model_path`, `public_id_field` and how to render — URL, label, optional `format_link` / `collect_metadata` / `get_url` overrides and `select_related` / `prefetch_related` for the resolve query. Apps `register()` their types in `AppConfig.ready()`, which eagerly compiles the per-type regex patterns (a `storage` and an `authoring` pattern for public-id types, one `id` pattern for id-based types).

Rendering and authoring are registered separately. A `LinkType` makes a marker renderable and validatable; a `PickerType` decides whether that type appears in the editor picker. Catalog `Location` is renderable because it is a `LinkableModel`, but it is not offered in the picker because it does not inherit `WikilinkableModel`. Citations register both a `LinkType` and a custom picker flow.

Two registration paths exist today:

- **Catalog** (`apps/catalog/apps.py`) walks every concrete `LinkableModel` and registers one type per model, named by its `entity_type` (`manufacturer`, `title`, `model`, …). This is model-driven — adding a linkable entity registers its wikilink automatically.
- **Citation** (`apps/citation/apps.py`) registers `cite` explicitly for `CitationInstance` (`public_id_field="slug"`), with a custom `format_link` that renders a footnote and a `collect_metadata` that builds the reference entry. Citations are the one type with no URL.

## Rendering

`render_markdown_html` (`apps/core/markdown/render.py`) is the pipeline: convert `[[type:id:pk]]` markers to ordinary markdown links, run markdown-it, sanitize with `nh3`, then convert task-list markers to checkboxes. A type with a `format_link` override renders its own way — `cite` becomes a superscript footnote (`<sup data-cite-id=…>`), and duplicate markers for the same target share one footnote index. When the caller passes `metadata_out`, each type's `collect_metadata` appends structured data (the citation reference list is built this way). A marker whose target was deleted renders as a broken-link placeholder rather than failing — deliberately: the marker stays in the text so the dangling reference is visible and fixable instead of silently vanishing.

The same renderer owns the plain-text projection. `render_markdown_plain` flattens rendered HTML into whitespace-normalized prose, and `render_markdown_field` returns `RenderedField(html, plain, citations)`. Catalog detail APIs expose this through `RichTextSchema`: `text` is storage converted back to authoring form for editors, `html` is display-ready, `plain` is for metadata/SEO/machine-readable descriptions, and `citations` is the structured footnote list.

## The reference graph — `RecordReference`

`RecordReference` (`apps/core/models/references.py`) is a polymorphic **record → record** edge: a `(source_type, source_id)` GenericForeignKey, a `(target_type, target_id)` GenericForeignKey, a unique constraint on the pair and an index on the target for "what links here". It is deliberately minimal — **it records only that record X links to record Y**. It has no `field_name`, no claim, no position: it does not know which field or claim the link lived in, only that the source record references the target record.

`sync_references(source, content)` (`apps/core/markdown/references.py`) is the **markdown → graph bridge**. It parses the storage-format content with every enabled type's pattern, groups the referenced pks by target model, diffs them against the source's existing rows and batch-creates the new edges and deletes stale edges for markers no longer present. Missing targets are skipped when creating new edges, but the graph is not target-lifecycle-enforced: if a target is deleted after an edge exists, the `RecordReference` row can remain while the marker remains in the source text. `register_reference_cleanup` wires a `post_delete` signal so deleting a source record drops all its outgoing edges.

### When the graph is populated

`sync_references` runs at **resolution**, keyed by the **resolved entity** (never by a claim): `_sync_markdown_references` (`apps/catalog/resolve/_entities.py`) runs after a claim-controlled entity is resolved, syncing every markdown field against its materialized winning value. Because every entity is resolved after a mutation — interactive _or_ ingest-origin — the graph covers all materialized content.

(A `save_inline_markdown_field` helper bundles convert + save + sync for a _direct_, non-claim markdown edit, but nothing calls it today — all catalog markdown is claim-controlled, so resolution is the only live sync path.)

### What the graph is and is not

Because the bridge runs against the materialized value keyed by the entity, `RecordReference` is an **active, entity-level** index: it reflects current resolved source content and answers "which records link to this one" cheaply. It does **not** record which claim or field held a link, it does **not** retain superseded historical versions, and it is not a substitute for checking whether the target row still exists. Any consumer that needs per-claim or historical reference data must read the claim log, not this graph.

`RecordReference` is **format-agnostic** — it is a plain record-to-record graph, and markdown is only its first populator. A future field in another textual language (YAML, JSON, …) that carries references would add its own bridge writing the same table, rather than changing the model. The markdown bridge is intentionally kept separable for exactly this reason.

## Related

- [Citations.md](Citations.md) — citations are a wikilink type (`cite`); inline `[[cite:…]]` markers render as footnotes and are indexed into this graph like any other link.
- [Provenance.md](Provenance.md) — markdown fields are claim-controlled, so a description's value is a claim and its links are synced at resolution time.
