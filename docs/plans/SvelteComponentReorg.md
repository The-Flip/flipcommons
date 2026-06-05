# Svelte Component Reorg

Reorganize `frontend/src/lib/components/` from a near-flat directory of ~180 files into role-based subfolders so a file's location communicates its purpose and dependency tier.

## Status: ✅ Implemented

This plan has been implemented.

## Why

The flat layout has no semantic structure. To find the right component for a task you have to already know its name — there's no way to browse by purpose, and no enforceable boundary between primitives and domain widgets.

The new layout adds that missing layer. Building a record edit page? `pages/record/edit/editors/` shows the section editors that exist. Adding a filter? `collections/filters/` shows what's already there. Writing a primitive? `ui/` is enforced domain-free, so a primitive can't quietly grow coupling to catalog logic without ESLint flagging it.

The cost is mostly mechanical (file moves + import updates). The win is durable: every future component lands in the right place by default.

## Current State

```text
frontend/src/lib/components/
  ~140 files at the top level
  form/         form fields + form/citation/
  cards/        Card + domain cards
  editors/      per-section editors + specs + save-claims helpers
  effects/      CoffeeStain
  grid/         generic grids
  media/        MediaCard, MediaGrid, etc.
```

## Target Structure

```text
frontend/src/lib/components/
  ui/                   true primitives — flat for one-offs + modal/, menu/, list/ clusters
  layout/               site chrome + page-level layout primitives
    site/               SiteShell, SiteHeader, Footer, Nav, etc.
    page/               Page, PageHeader, TwoColumnLayout, Breadcrumb + sidebar/ cluster
  input/                basic controls + picker/, citation/, markdown/ role folders + internal/
  collections/          collection-display widgets
    cards/              Card + domain cards
    grid/               generic grids
    filters/            FilterDrawer, etc.
  effects/              decorative overlays — CoffeeStain, WearEffect
  media/                unchanged
  pages/                page-kind shells
    record/             single-record pages
      detail/           RecordDetailShell + Taxonomy*/Simple*/Hierarchical* detail layouts, etc.
      create/           CreatePage
      edit/             EditSection*/SectionEditor* + Taxonomy*/Simple* edit layouts, etc.
        editors/        per-section editors + edit-section specs
      edit-history/     EditHistory
      sources/          EntitySources
      delete/           DeletePage, etc.
    listing/            TaxonomyListPage, etc.
    error/              ErrorPage
  provenance/           claims, attribution, qualifiers
  markdown/             rich-text rendering — Markdown + accordions + inline citation rendering
  entity-links/         UserLink, LocationLink
```

## Conventions

1. **Co-locate** `*.test.ts`, `*.dom.test.ts`, `*.fixture.svelte`, `*.test-harness.svelte` with the component they exercise.
2. **One folder, one concept.** If a file plausibly belongs in two folders, the boundary is wrong — rename or merge before adding the file.
3. **No barrel `index.ts`** re-exports. Direct imports keep Vite tree-shaking honest and avoid circular-import traps. Cost: deep import paths (e.g. `$lib/components/pages/record/edit/editors/specs/title-edit-sections`). If this proves painful in practice, scoped path aliases (`$editors` → `$lib/components/pages/record/edit/editors`) via `kit.alias` are the escape hatch — don't reintroduce barrels.

## Enforcement

Four boundaries are ESLint-enforced via `no-restricted-imports` (see [the config](../../frontend/eslint.config.js)):

- **`ui/`** — primitives-only: may not import from any sibling components folder.
- **`pages/`** — page bodies: importable only from `routes/` and within `pages/`.
- **`layout/site/`** — site-chrome shells (`SiteShell` etc.): importable only from `routes/`, which wire them into the root layout. (Page-level head/SEO components — `MetaTags`, `JsonLd` — are deliberately **not** here; they live in `layout/page/head/` so page shells can set their own head tags. That split is what makes `layout/site/` cleanly routes-only.)
- **`$lib` → `routes/`** — `$lib` may not import from `routes/`. This is the boundary the route-private convention and the switch-promotion decisions rely on: shared code goes in `$lib`, single-route code stays route-private. Test files are exempt (route-loader tests legitimately import `+layout.server`).

The `pages/` rule already covers the `layout/page/` → `pages/` direction — a `layout/` file importing a page shell fails CI today.

Everything else is convention — readable in the tree, explained in folder READMEs, but not policed:

- `provenance/` and `markdown/` are nominally display-only; a form component drifting in wouldn't fail CI.
- `input/` is nominally input-only; same caveat.

We accept the convention-only enforcement for these because policing "what does this file contain" via import rules is awkward and tends to false-positive. The four rules above all police "who may import this folder" (a structural fact ESLint matches reliably), not file contents. Content drift is caught in code review, not tooling.

## Folder READMEs

A select few folders get a short `README.md` explaining what belongs there — flagged in the relevant `### folder` sections under Sequencing. Most don't: the folder name is self-explanatory and a README would just restate it.

**Format:** "This folder contains components that..." and what does NOT go in the folder, if applicable. If that's not enough, say the rule that distinguishes "belongs here" from "doesn't," any boundary constraint.

Do NOT list files, or mention the location of where invalid files DO go (just say elsewhere), or restate the folder name: those cause doc rot. 4 lines max.

## Out of Scope

- Renaming, splitting, merging, adding components.
- Any form of behavior change.
- Storybook or Histoire adoption.

## Process

All work is in a single PR. Each section below is one commit. Each commit is mechanical moves + import updates + (where appropriate) one new ESLint rule.

**Each commit will be reviewed**. 🛑 STOP for user review before committing.

**Normalize imports on touch** — when a move makes you edit a file's imports, bring all of that file's imports into line with the `$lib` rule in [Svelte.md](../Svelte.md) (same-folder → `./`, cross-folder → `$lib`), not just the specifier that changed. Leave files you aren't already editing untouched.

**Codemod** — use `frontend/scripts/codemod/move-components.mjs --to <folder> <Stem>...` for every move (run it from the `frontend/` directory). It `git mv`s each file (and its co-located tests/fixtures) so rename detection holds, then rewrites imports in every touched file to the project convention (same-folder → `./`, cross-folder → `$lib`). It only opens files that move or import a moved file; others are left untouched. Don't hand-edit import paths. Stems resolve at the top level of `lib/components/`; to move files already in a subfolder, pass `--from <subfolder>` (e.g. `--from cards --to collections/cards`) — with `--from` and no stems, the whole subfolder moves. The codemod leaves the now-empty source dir behind; `rmdir` it.

**Update config path references by hand** — the codemod rewrites JS/TS import specifiers only, not file paths in config. `frontend/.stylelintrc.cjs` has per-file `overrides` (e.g. the `:global` exemptions for `Prose.svelte`, `Card.svelte`, `WearEffect.svelte`); when you move one of those files, repoint its override path or the pre-commit stylelint hook fails. Grep `.stylelintrc.cjs` (and `knip.jsonc`) for any moved stem before committing.

**Resolve "decide on inspection" punts BEFORE the move commit they belong to**, not during. Doing it during the move puts momentum-pressure on picking "wherever's easiest" rather than the right home. `grep -rc` each ambiguous file's identifier, then commit.

**Per-commit verification gate**. Each commit must pass:

- `pnpm svelte-check` (catches import path errors and type drift)
- `pnpm lint` (prettier + eslint + stylelint — run before committing; stylelint catches stale per-file `overrides` paths in `.stylelintrc.cjs` when a moved file had a `:global` exemption, which otherwise only fails inside the pre-commit hook)
- `make test` (runs vitest + pytest)
- `pnpm build` (production Vite build — circular-import and tree-shaking failures only surface in build, not dev/HMR)

## Sequencing

### `ui/` - DONE ✅

Move true primitives (domain-free, no internal composition) from the top level into `ui/`:

```text
ui/
  Button.svelte
  FaIcon.svelte
  Avatar.svelte, Prose.svelte
  ChipGroup.svelte, PillSelect.svelte
  SearchBox.svelte, StatusMessage.svelte
  SmartDate.svelte, LastUpdated.svelte
  InlineDiff.svelte
  AccordionSection.svelte
  modal/
    Modal.svelte, Dialog.svelte, scroll-lock.ts
  menu/
    ActionMenu.svelte, MenuItem.svelte, MenuDivider.svelte, MenuSectionHeader.svelte
  list/
    List.svelte, ListItem.svelte
```

**Delete `LinkButton.svelte`** — zero importers in the codebase (confirmed by the usage audit script at `/tmp/audit-component-usage.py`).

#### ESLint rule

**Rule:** `ui/` is domain-free and primitives-only. Nothing in `ui/` may import from any other components folder. Dependency direction flows outward only — everything else may import from `ui/`, never back.

Extend ESLint to enforce two boundaries (added together in this commit, since they share the `no-restricted-imports` config block):

1. **`ui/` may not import from any sibling components folder.** Domain stays out of primitives.
2. **`pages/**`may only be imported from`routes/**`and within`pages/**`.\*\* Page-shells are for routes; importing one from a general component is always a mistake.

**Important:** `frontend/eslint.config.js` has explicit guidance (around the `no-restricted-imports` block) that flat-config rule options do NOT union across overrides — the last matching block wins, silently dropping earlier restrictions. So either:

- merge both new restrictions into the existing `no-restricted-imports` block (preferred), or
- duplicate the existing posthog-js and `$lib/api/internal` restrictions into any narrower override.

Naively adding separate override blocks will silently drop the existing vendor-boundary restrictions for files under the new scopes.

#### Add `ui/README.md`

```markdown
# ui

This folder contains true primitives: components with no internal structure of
their own, such as Button and Modal.

`ui/` may not import from any sibling components folder. Everything else may
import from `ui/`.

If a component composes other components or knows about domain concepts, it
doesn't belong here.
```

### `effects/` - DONE ✅

Move `WearEffect.svelte` from `cards/` into `effects/` alongside `CoffeeStain.svelte`. Both are decorative SVG/CSS overlays applied to other components; neither is card-specific. `WearEffect` is currently parked under `cards/` because `Card` consumes it, not because it belongs there.

### `collections/` - DONE ✅

Create `collections/` and move existing `cards/` and `grid/` under it. `grid/` also holds `InfiniteScroll` and `ServerPaginatedList` — they ride the wholesale `grid/` → `collections/grid/` move with the rest of the family. Move the top-level generic filter primitives in:

- `collections/filters/`: FilterDrawer, FilterChip, ActiveFilterChips

The domain filter sidebars (`TitleFilterSidebar`, `ManufacturerFilterSidebar`) are **not** placed here — each has a single route consumer, so by the route-private convention they go to `routes/.../_components/` (see route-private section).

`TitleList` (composes `CardGrid` + `TitleCard`) goes at **`collections/` top level**: used by `series/[slug]` and `franchises/[slug]` _detail_ pages — two route families, embedded section, not a page shell, not `pages/listing/`.

`CatalogListRow` (the standard name + count row content for the paginated listing pages) also sits at **`collections/` top level** — already created there during the SSR listing work.

`CreateFirstModelPrompt` and `ManufacturerCardGrid` are **not** placed here despite being collection-shaped — both have single consumers, so by the route-private convention they go to `routes/.../_components/`. (`CreateFirstModelPrompt` and its sibling `CreateFirstCorporateEntityPrompt` already live route-private under `routes/titles/[slug]/_components/` and `routes/manufacturers/[slug]/_components/`; `ManufacturerCardGrid` already lives route-private under `routes/locations/[...path]/_components/` — see the follow-up below. See route-private section. The earlier "domain composition, so collections/" reasoning was category-over-usage — the same anti-pattern we rejected for `NeedsReviewBanner`. Promote to `collections/` only when a second consumer appears.)

Add `collections/README.md`:

```markdown
This folder contains components for displaying collections of items.

- `cards/` — display single item as a card
- `grid/` — display grid of cards
- `filters/` — UI for narrowing which items show: filter sidebar, chips, drawers.
```

### `layout/` - DONE ✅

Move site chrome and page-level layout primitives from the top level, split into two subfolders.

**`layout/site/`** — chrome wrapping all content:

- SiteShell, MinimalSiteShell, FocusSiteShell
- SiteHeader, Footer, Nav
- Wordmark

ESLint-enforced routes-only (see Enforcement): only `routes/` imports these — the shells are wired into the app by the root layout. The folder is flat, so within-folder composition (`SiteShell` → `SiteHeader`) uses same-folder `./` and isn't caught by the rule. Head/SEO components (`MetaTags`, `JsonLd`) are **not** here — they're set per page, so they live in `layout/page/head/` where page shells can import them.

**`layout/page/`** — composition primitives used inside a page:

- Page, PageHeader, PageActionBar
- TwoColumnLayout
- FocusContentShell
- Breadcrumb

**`layout/page/head/`** — document-`<head>` emitters, set per page (not site chrome):

- MetaTags + meta-tags.ts
- JsonLd + jsonld.ts

**`layout/page/sidebar/`** — content primitives for the sidebar slot of `TwoColumnLayout`:

- SidebarSection
- SidebarList, SidebarListItem
- ExpandableSidebarList — generic "show first N, then _Show all_" wrapper around `SidebarList`. Currently only used by manufacturer "Notable People", but it's a generic; other long sidebar lists (model credits, etc.) are candidates to adopt it in the future.

These are page-layout-coupled, not generic primitives — their styling (small font, hairline separators, edit-button affordance) assumes a narrow sidebar context.

Add `layout/README.md`: two lines naming the `site/` vs `page/` split — site chrome wraps all content; page primitives compose within one page.

### `provenance/` - DONE ✅

Move the claim/attribution cluster from the top level:

- ClaimDisplay, ClaimValue + claim-display.ts
- ClaimAuthor, ClaimAttribution
- AttributionLine
- qualifier-renderers.ts (qualifiers are a provenance concept)

`NeedsReviewBanner` is conceptually provenance but currently single-route — see route-private section below.

`EditHistory` and `EntitySources` are the body of their own page-kinds (`pages/record/edit-history/` and `pages/record/sources/`), not cross-cutting provenance widgets. See the `pages/` section.

Add `provenance/README.md`:

```markdown
This folder contains components that display the provenance of catalog records. Editing of claim values happens elsewhere.
```

### `markdown/` - DONE ✅

Create top-level `markdown/` as the display-side rich-text rendering subsystem. Citation display is part of this subsystem — every shared citation rendering component is currently consumed only by the markdown pipeline. (The other place citations are rendered, `EntitySources.svelte`, uses its own inline template and doesn't share components with this folder.)

Move from the top level:

- `Markdown.svelte` — renders pre-rendered HTML through `Prose`, optionally layering citation tooltips and a references section
- `CitationTooltip.svelte` + `citation-tooltip.ts` — inline citation-marker tooltip, only consumed by Markdown
- `citation-refs.ts` — citation ref navigation helpers, only used inside the markdown pipeline
- `ReferencesSection.svelte` — rendered inside Markdown body and inside `RichTextReferencesAccordion`
- `RichTextOverviewAccordion.svelte` — catalog detail-page accordion that wraps Markdown
- `RichTextReferencesAccordion.svelte` — catalog detail-page accordion that wraps `ReferencesSection`
- `rich-text-accordion-state.svelte.ts` — shared state for the two accordions

There is no top-level `citation/` folder. Citation editing fields live in `input/citation/` (see the `input/` section). If a scalar-citation renderer ever shows up sharing code with `EntitySources`, that's the cue to extract a citation primitives folder — but today there's nothing to extract.

Add `markdown/README.md`:

```markdown
This folder contains components that render rich text: markdown output plus the
citation tooltips and references that get layered onto it.

These components only do display; editing markdown and citations lives elsewhere.
```

### `input/`

Input components — anything that captures user input, from a bare `TextField` to a composed `MarkdownTextArea` or `WikilinkAutocomplete`. Named `input/` rather than `form/` because not all of these live in a `<form>` (e.g. `SearchableSelect` in a filter sidebar, `MarkdownTextArea` in a comment box).

```text
input/
  # basic controls — type a value
  TextField.svelte
  NumberField.svelte
  YearRangeInput.svelte
  TagInput.svelte                    # enter free-form tags (you type values — there's no list to pick from)
  Fieldset.svelte
  FieldGroup.svelte
  link-types-fixtures.ts

  picker/                            # the user picks from a list of options
    MonthSelect.svelte               #   a month
    SearchableSelect.svelte          #   one or many from a fixed set shown in-page
    entity-select/                   #   one or many catalog entities, searched as you type
      EntitySelect.svelte
      EntityMultiSelect.svelte
      EntityCombobox.svelte
    internal/
      ComboboxListbox.svelte         #   shared listbox shell for the pickers above

  citation/                          # add & edit citations
    CitationAutocomplete.svelte      #   the source-picker flow (opened from a field OR from markdown)
    CitationSearchStage.svelte
    CitationIdentifyBySearchStage.svelte
    CitationCreateStage.svelte
    CitationLocatorStage.svelte
    EditCitationField.svelte         #   the flow as a standalone form field
    NotesAndCitationsDetails.svelte  #   notes + citations form section (record create/edit/delete pages)
    citation-fixtures.ts, citation-types.ts

  markdown/                          # write rich text
    MarkdownTextArea.svelte
    MarkdownToolbar.svelte
    markdown-shortcuts.ts
    wikilink/                        # insert [[wikilinks]] while writing (a markdown-only feature)
      WikilinkAutocomplete.svelte
      wikilink-helpers.ts

  internal/                          # shared plumbing — no user-facing role of its own
    DropdownHeader.svelte            #   dropdown chrome shared by the citation stages & wikilink
    DropdownItem.svelte
    DropdownSearchInput.svelte
    search-helpers.ts                #   createDebouncedSearch — used by citation, wikilink & entity-select
```

Basic controls (TextField, NumberField, etc.) stay flat — they're the noisy majority and a `fields/` subfolder would just add a layer without value. `Fieldset` and `FieldGroup` are layout primitives (the wrapper you put a control in, used in and out of forms); they stay flat too.

Everything else is grouped by **what the user is doing** — the role a control plays, not its implementation. `MonthSelect` (native `<select>`) and `SearchableSelect` (filtered combobox) are both pickers; `TagInput` looks adjacent but isn't — you type values, there's no list — so it stays with the basic controls. Grouping by role keeps controls findable and sits related ones together before they share code, surfacing convergence candidates the flat layout hid.

`internal/` holds shared plumbing and lives at the lowest common ancestor of its consumers. `ComboboxListbox` is used only by the pickers → `picker/internal/`. The dropdown chrome and `createDebouncedSearch` span citation, wikilink and entity-select → `input/internal/`. Consumers never reach into a sibling's `internal/`. (`formatCitationResult` moves out of `search-helpers.ts` into `citation/` — it's citation-specific, not plumbing.)

`citation/` is a peer folder rather than nested under `markdown/` because its flow is launched from **both** a standalone form field (`EditCitationField`) and the wikilink overlay (`[[cite:` redirect); `wikilink/` nests under `markdown/` because inserting `[[wikilinks]]` is purely a markdown-editing feature with no other consumer.

### `pages/` - DONE ✅

Build out `pages/record/{detail,create,edit,edit-history,sources,delete}/`, `pages/listing/`, `pages/error/` and move the page-shell components in. Also move the existing top-level `editors/` folder to `pages/record/edit/editors/`. The "Taxonomy\*" components are catalog page scaffolds despite the name, and route usage determines page-kind.

Add `pages/README.md`:

```markdown
This folder contains page shell components. Each subfolder corresponds to a SvelteKit route pattern (`record/detail/` ↔ `/[entity]/[slug]/`, `record/edit/` ↔ `/[entity]/[slug]/edit/[section]/`, etc.). Adding a new page-kind means adding a subfolder under the matching parent.
```

**`pages/record/detail/`**

- RecordDetailShell
- HeroHeader (only consumer is RecordDetailShell; not generic enough for layout/page/)
- TaxonomyDetailBaseLayout (used by gameplay-features, themes)
- SimpleTaxonomyDetailLayout (used by 8 simple-taxonomy routes)
- HierarchicalTaxonomySidebar (gameplay-features, themes)
- HierarchicalTaxonomyChildrenAccordion (gameplay-features, themes)
- HierarchicalTaxonomyMobileMetaBar (gameplay-features, themes)
- TaxonomyLinkSidebarSection (used on Title and Model detail layouts, not just taxonomies)
- Detail-page sections and sidebars from old `catalog/`:
  - ModelSpecsSidebar, ModelHierarchy
  - CreditsList
  - ExternalLinksSidebarSection

If `pages/record/detail/` gets crowded, consider a `pages/record/detail/sections/` subfolder. Decide on inspection of the final count.

**`pages/record/create/`**

- CreatePage

**`pages/record/edit/`**

- EditSectionShell
- SectionEditorHost, SectionEditorForm, SectionEditorModal
- EditRedirectFallback
- TaxonomyEditSectionPageBase, TaxonomyEditSectionLayoutBase
- SimpleTaxonomyEditSectionLayout, SimpleTaxonomyEditSectionPage

`EditSectionMenu` + `edit-section-menu.ts` are **not** edit-page-body — they're the dropdown rendered by `layout/page/PageActionBar.svelte` (the edit/history/sources action menus in the page action bar). Moving them into `pages/` would make a `layout/` primitive import from `pages/`, violating the boundary. They move to `layout/page/` alongside their host; the edit shells here import them from there.

**`pages/record/edit/editors/`**

The existing top-level `editors/` folder (76 files) moves here, with an internal split that pulls the `.ts` plumbing out of the components. Two files currently parked under `routes/` also join — they're cross-route or depended on by lib, so they belong in $lib:

- `routes/models/[slug]/edit/ModelEditorSwitch.svelte` → `pages/record/edit/editors/` (also imported by `routes/titles/[slug]/+layout.svelte` via an awkward `../../models/...` relative path)
- `routes/systems/[slug]/edit/save-system-claims.ts` → `pages/record/edit/editors/entity/system/` (imported by `lib/components/editors/SystemManufacturerEditor.fixture.svelte` and `SystemTechnologyEditor.fixture.svelte` — `$lib` shouldn't depend on `routes/`)

```text
editors/
  # Shared at root
  NameEditor, DescriptionEditor, MediaEditor, AliasesSectionEditor (+ tests + fixtures)
  edit-section-def.ts, editor-contract.ts, edit-action-context.ts, edit-layout-context.ts
  save-claims-shared.ts (+ test)
  combined-edit-sections.ts (+ test)       # cross-entity composition

  entity/                                  # everything specific to editing one entity type
    model/
      ModelEditorSwitch.svelte             # promoted from routes/models/[slug]/edit/
      BasicsEditor, FeaturesEditor, PeopleEditor, RelatedModelsEditor,
        ExternalDataEditor, TechnologyEditor (+ tests + fixtures)
      model-edit-sections.ts (+ test)
      model-edit-options.ts
      save-model-claims.ts (+ test)
    title/                                 # TitleEditorSwitch stays route-private (single-route)
      TitleExternalDataEditor, TitleFranchiseEditor (+ tests + fixtures)
      title-edit-sections.ts
      title-edit-options.ts
      save-title-claims.ts (+ test)
    system/                                 # SystemEditorSwitch stays route-private (single-route)
      SystemManufacturerEditor, SystemTechnologyEditor (+ tests + fixtures)
      system-edit-sections.ts
      system-edit-options.ts
      save-system-claims.ts                # promoted from routes/systems/[slug]/edit/ (lib fixtures depend on it)
    taxonomy/
      HierarchicalTaxonomyEditorSwitch.svelte
      SimpleTaxonomyEditorSwitch.svelte
      ParentsSectionEditor (hierarchical-only),
        DisplayOrderEditor (simple-only) (+ tests + fixtures)
      hierarchical-taxonomy-edit-sections.ts
      hierarchical-taxonomy-edit-types.ts
      simple-taxonomy-edit-sections.ts
      simple-taxonomy-edit-types.ts
    # person/manufacturer/corporate-entity/location: only the edit-sections spec lives
    # in lib (already there); their switch + per-entity section editor + save-claims +
    # edit-types stay route-private (each is single-route — see "Switch promotions" below).
    person/
      person-edit-sections.ts
    manufacturer/
      manufacturer-edit-sections.ts (+ test)
    corporate-entity/
      corporate-entity-edit-sections.ts
    location/
      location-edit-sections.ts
```

**Why per-entity bucketing:** the entity/ split makes "what does Model edit?" one folder-listing away — switch + per-section editors + spec + save are all together. Shared editors live at the root as a small, deliberate set. Cross-checked usage confirms no straddlers — every editor is either used by 2+ entity switches (shared) or by exactly one (per-entity).

**Switch promotions — only what crosses the `$lib` boundary moves.** A switch earns a `$lib` home only when something outside its own route family consumes it. Audited reality:

- **`ModelEditorSwitch`** is consumed cross-route — `routes/titles/[slug]/+layout.svelte` reaches into `../../models/[slug]/edit/ModelEditorSwitch.svelte` (single-model titles embed the model editor). Promote it to `editors/entity/model/`; that awkward relative path becomes a `$lib` import.
- **`save-system-claims.ts`** is consumed by two `$lib` fixtures (`SystemManufacturerEditor.fixture.svelte`, `SystemTechnologyEditor.fixture.svelte`). Promote it to `editors/entity/system/` so `$lib` no longer reaches into `routes/`.
- **The other 6 switches (Title, System, Person, Manufacturer, CorporateEntity, Location) stay route-private.** Each is imported only within its own route family (`+layout.svelte` + `edit/[section]/+page.svelte`), and each owns a route-local cluster the switch imports via `./` — a per-entity section editor (`ManufacturerBasicsEditor`, `LocationBasicsEditor`/`LocationDivisionsEditor`, `PersonDetailsEditor`, `CorporateEntityBasicsEditor`), its `save-*-claims.ts`, and its `*-edit-types.ts`. Promoting the switch would drag that single-route cluster into shared `$lib` and recreate the `$lib`→`routes` smell. They are textbook route-private and stay put.

The Model/Title split in `$lib` is **not** incidental: Model/Title editing is already fully `$lib`-ized (zero route-local edit deps), while the other entities each retain a route-local edit cluster. Only the per-entity `*-edit-sections.ts` spec — already in `$lib` and consumed by the generic edit framework — lives under `editors/entity/X/` for those entities; the rest of their cluster stays beside the route.

Add `pages/record/edit/editors/README.md` explaining what makes a file a section editor — the spec / save-claims contract isn't obvious from filenames.

**`pages/record/edit-history/`**

The `/[entity]/[slug]/edit-history/` route across catalog entity types renders only `<EditHistory />`. The component is the page.

- EditHistory

`change-display.ts` is **not** edit-history-private — it's a shared change/claim-value display helper also consumed by `provenance/ClaimValue.svelte` and `routes/changesets/`. It moves to `provenance/` (its functions render the provenance of changes); `EditHistory`, a page, imports it from there.

**`pages/record/sources/`**

The `/[entity]/[slug]/sources/` route across catalog entity types renders only `<EntitySources />`. Same pattern as edit-history.

- EntitySources + entity-sources.ts

**`pages/record/delete/`**

- DeletePage + delete-page.ts

**`pages/listing/`**

- TaxonomyListPage (display-types, technology-generations — the SSR listing work migrated the other taxonomy routes to `CatalogListing`)
- GroupedTaxonomyList (technology-generations, display-types)
- NoResultsCreatePrompt — used by TaxonomyListPage + 3 listing routes; reused, so it belongs here. (`CreateFirstModelPrompt` and `CreateFirstCorporateEntityPrompt` are single-route — route-private, see below.)
- PaginatedListPage, CatalogListing, FacetedCatalogListing, PaginatedListLoader — the SSR listing controllers and their shared host: `PaginatedListPage` (row-list controller), `CatalogListing` (catalog adapter over `PaginatedListPage`, resolving a `catalogKey` via `ENTITY_META`), `FacetedCatalogListing` (filter-sidebar card-grid controller, used by the titles and manufacturers listing pages) and `PaginatedListLoader` (loader host shared by both controllers). Already created here during the SSR listing work (not moves).

**`pages/error/`**

- ErrorPage

### `entity-links/` - DONE ✅

`UserLink` (1 consumer: `ClaimAuthor` in `provenance/`) and `LocationLink` (3 files across `corporate-entities/` and `manufacturers/`) are small route-aware entity links. `ui/` is out (they know about routes). Splitting them — UserLink to `provenance/`, LocationLink somewhere — leaves LocationLink in an awkward single-occupant home given its cross-route use.

Create top-level `entity-links/` as a small family folder for the pair.

```text
entity-links/
  UserLink.svelte
  LocationLink.svelte
```

### `routes/.../_components/` - DONE ✅

Components used by only one route family belong next to that route, not in `$lib`. SvelteKit treats directories starting with `_` as non-routable, so `routes/foo/_components/Bar.svelte` is a route-private home that won't accidentally become `/foo/_components`.

**Mechanism:** the candidate list below was derived by running the usage-audit script at `/tmp/audit-component-usage.py` (output at `/tmp/component-usage.md`). The script enumerates every component under `lib/components/`, finds its direct importers, and buckets by route-family count. **Re-run before executing this step** — the codebase shifts and prior classifications go stale.

The script has two known limitations to apply manual judgment for:

1. **Transitive multi-route reach.** A single-direct-route component whose only lib consumer is itself multi-route is effectively multi-route. The script only checks one hop; verify manually before committing a move.
2. **Subsystem-coherence override.** Files inside `editors/` are kept together even when an audit shows a single direct route (e.g. `BasicsEditor` only via `ModelEditorSwitch`). The subsystem grouping wins because the editor framework is a coherent unit.

**Root-layout exception:** `routes/+layout.svelte` (the root layout serving every page) is treated as "site-wide," not as a single route family. Components used only by the root layout (`SiteShell`, `MinimalSiteShell`, `FocusSiteShell`) stay in `layout/site/`, not route-private.

**Candidates from the audit:**

- `ThemeSwitcher` → `routes/style-lab/_components/` (only `routes/style-lab/+page.svelte`).
- `TitleFilterSidebar` → `routes/titles/_components/` (only `routes/titles/+page.svelte`).
- `ManufacturerFilterSidebar` → `routes/manufacturers/_components/` (only `routes/manufacturers/+page.svelte`).
