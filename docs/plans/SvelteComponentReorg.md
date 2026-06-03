# Svelte Component Reorg

## Goal

Reorganize `frontend/src/lib/components/` from a near-flat directory of ~180 files into role-based subfolders so a file's location communicates its purpose and dependency tier.

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
  input/                base fields + citation/, dropdown/, markdown/, wikilink/ subsystems
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

## What's Enforced vs Convention

Only `ui/` (no imports from any sibling components folder) and `pages/` (importable only from `routes/` and within `pages/`) are ESLint-enforced. Everything else in this plan is convention — readable in the tree, explained in folder READMEs, but not policed:

- `layout/page/` could quietly import from `pages/record/detail/` and nothing would stop it.
- `provenance/` and `markdown/` are nominally display-only; a form component drifting in wouldn't fail CI.
- `input/` is nominally input-only; same caveat.

We accept the convention-only enforcement for these because policing "what does this file contain" via import rules is awkward and tends to false-positive. Drift will be caught in code review, not tooling.

## Folder READMEs

A select few folders get a short `README.md` explaining what belongs there — flagged in the relevant `### folder` sections under Sequencing. Most don't: the folder name is self-explanatory and a README would just restate it.

**Format:** "This folder contains components that..." and what does NOT go in the folder, if applicable. If that's not enough, say the rule that distinguishes "belongs here" from "doesn't," any boundary constraint.

Do NOT list files, or mention the location of where invalid files DO go (just say elsewhere), or restate the folder name: those cause doc rot. 4 lines max.

## Out of Scope

- Renaming, splitting, merging, adding components.
- Any form of behavior change.
- Storybook or Histoire adoption.

## Sequencing

All work is in a single PR. Each section below is one commit. Each commit is mechanical moves + import updates + (where appropriate) one new ESLint rule.

**Each commit will be reviewed**. 🛑 STOP for user review before committing.

**Normalize imports on touch** — when a move makes you edit a file's imports, bring all of that file's imports into line with the `$lib` rule in [Svelte.md](../Svelte.md) (same-folder → `./`, cross-folder → `$lib`), not just the specifier that changed. Leave files you aren't already editing untouched.

**Codemod** — use `scripts/codemod/move-components.mjs --to <folder> <Stem>...` for every move. It `git mv`s each file (and its co-located tests/fixtures) so rename detection holds, then rewrites imports in every touched file to the project convention (same-folder → `./`, cross-folder → `$lib`). It only opens files that move or import a moved file; others are left untouched. Don't hand-edit import paths.

**Resolve "decide on inspection" punts BEFORE the move commit they belong to**, not during. Doing it during the move puts momentum-pressure on picking "wherever's easiest" rather than the right home. `grep -rc` each ambiguous file's identifier, then commit.

**Per-commit verification gate**. Each commit must pass:

- `pnpm svelte-check` (catches import path errors and type drift)
- `make test` (runs vitest + pytest)
- `pnpm build` (production Vite build — circular-import and tree-shaking failures only surface in build, not dev/HMR)

### `ui/`

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

### `collections/`

Create `collections/` and move existing `cards/` and `grid/` under it. `grid/` now also holds `InfiniteScroll` and `ServerPaginatedList` (added during the SSR listing work) — they ride the wholesale `grid/` → `collections/grid/` move with the rest of the family. Move the top-level filter files in, and the domain filter sidebars:

- `collections/filters/`: FilterDrawer, FilterChip, ActiveFilterChips, SidebarSkeleton, TitleFilterSidebar, ManufacturerFilterSidebar, ManufacturerActiveFilterChips

`TitleList` (composes `CardGrid` + `TitleCard`) goes at **`collections/` top level**: used by `series/[slug]` and `franchises/[slug]` _detail_ pages — two route families, embedded section, not a page shell, not `pages/listing/`.

`CatalogListRow` (the standard name + count row content for the paginated listing pages) also sits at **`collections/` top level** — already created there during the SSR listing work.

`CreateFirstModelPrompt` and `ManufacturerCardGrid` are **not** placed here despite being collection-shaped — both have single consumers, so by the route-private convention they go to `routes/.../_components/`. (See route-private section. The earlier "domain composition, so collections/" reasoning was category-over-usage — the same anti-pattern we rejected for `NeedsReviewBanner`. Promote to `collections/` only when a second consumer appears.)

Add `collections/README.md`:

```markdown
This folder contains components for displaying collections of items.

- `cards/` — display single item as a card
- `grid/` — display grid of cards
- `filters/` — UI for narrowing which items show: filter sidebar, chips, drawers.
```

### `layout/`

Move site chrome and page-level layout primitives from the top level, split into two subfolders.

**`layout/site/`** — chrome wrapping all content:

- SiteShell, MinimalSiteShell, FocusSiteShell
- SiteHeader, Footer, Nav
- Wordmark
- MetaTags + meta-tags.ts
- JsonLd + jsonld.ts

**`layout/page/`** — composition primitives used inside a page:

- Page, PageHeader, PageActionBar
- TwoColumnLayout
- FocusContentShell
- Breadcrumb

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

Input components — anything that captures user input, from a bare `TextField` to a composed `MarkdownTextArea` or `WikilinkAutocomplete`. Named `input/` rather than `form/` because not all of these live in a `<form>` (e.g. `SearchableSelect` in a filter sidebar, `MarkdownTextArea` in a comment box); "input" follows MUI's "Inputs" convention, which spans both bare controls and rich composed widgets (MUI files Autocomplete there too). Apply an internal split that gives each input subsystem its own subfolder.

```text
input/
  TextField.svelte
  NumberField.svelte
  MonthSelect.svelte
  TagInput.svelte
  YearRangeInput.svelte                       # moves in from components/ top level
  SearchableSelect.svelte (+ test)            # moves in from components/ top level
  Fieldset.svelte
  FieldGroup.svelte + tests + fixtures
  link-types-fixtures.ts
  citation/
    CitationAutocomplete.svelte (+ test)
    CitationCreateStage.svelte
    CitationIdentifyBySearchStage.svelte
    CitationLocatorStage.svelte
    CitationSearchStage.svelte
    EditCitationField.svelte (+ test)        # moves in from input/ top level
    NotesAndCitationsDetails.svelte           # moves in from components/ top level
    citation-fixtures.ts, citation-types.ts (+ test)
  dropdown/
    DropdownHeader.svelte, DropdownItem.svelte, DropdownSearchInput.svelte
    search-helpers.ts + test
  markdown/
    MarkdownTextArea.svelte + tests
    MarkdownToolbar.svelte + test
    markdown-shortcuts.ts + test
  wikilink/
    WikilinkAutocomplete.svelte + test
    wikilink-helpers.ts + test
```

Base field primitives (TextField, NumberField, etc.) stay flat — they're the noisy majority and pulling them into a `fields/` subfolder would just add a layer without value. `Fieldset` and `FieldGroup` are input-layout primitives (the wrapper you put a control in, used in and out of forms); they stay flat alongside the controls rather than getting their own `form/` folder — two files don't warrant the split, and `FieldGroup` isn't form-specific anyway. Each subsystem subfolder (`citation/`, `dropdown/`, `markdown/`, `wikilink/`) groups input UI for one well-defined system.

**Principle:** `input/` is for input components, organized by subsystem where one exists. Top-level subsystem folders (`markdown/`, `provenance/`) hold display-side UI for those same subsystems. The input/display distinction is real and stays.

Add `input/README.md`:

```markdown
This folder contains input components. Base fields live at the top level; each input subsystem (`citation/`, `dropdown/`, `markdown/`, `wikilink/`) in a subfolder.

Display components (such as for markdown and citations) live elsewhere.
```

### `pages/`

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
  - RatingsSidebarSection, ExternalLinksSidebarSection

If `pages/record/detail/` gets crowded, consider a `pages/record/detail/sections/` subfolder. Decide on inspection of the final count.

**`pages/record/create/`**

- CreatePage

**`pages/record/edit/`**

- EditSectionShell
- EditSectionMenu + edit-section-menu.ts
- SectionEditorHost, SectionEditorForm, SectionEditorModal
- EditRedirectFallback
- TaxonomyEditSectionPageBase, TaxonomyEditSectionLayoutBase
- SimpleTaxonomyEditSectionLayout, SimpleTaxonomyEditSectionPage

**`pages/record/edit/editors/`**

The existing top-level `editors/` folder (76 files) moves here, with an internal split that pulls the `.ts` plumbing out of the components. Two files currently parked under `routes/` also join — they're cross-route or depended on by lib, so they belong in $lib:

- `routes/models/[slug]/edit/ModelEditorSwitch.svelte` → `pages/record/edit/editors/` (also imported by `routes/titles/[slug]/+layout.svelte` via an awkward `../../models/...` relative path)
- `routes/systems/[slug]/edit/save-system-claims.ts` → `pages/record/edit/editors/save/` (imported by `lib/components/editors/SystemManufacturerEditor.fixture.svelte` and `SystemTechnologyEditor.fixture.svelte` — `$lib` shouldn't depend on `routes/`)

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
    title/
      TitleEditorSwitch.svelte             # promoted from routes/titles/[slug]/edit/
      TitleExternalDataEditor, TitleFranchiseEditor (+ tests + fixtures)
      title-edit-sections.ts
      title-edit-options.ts
      save-title-claims.ts (+ test)
    system/
      SystemEditorSwitch.svelte            # promoted from routes/systems/[slug]/edit/
      SystemManufacturerEditor, SystemTechnologyEditor (+ tests + fixtures)
      system-edit-sections.ts
      system-edit-options.ts
      save-system-claims.ts                # promoted from routes/systems/[slug]/edit/
    taxonomy/
      HierarchicalTaxonomyEditorSwitch.svelte
      SimpleTaxonomyEditorSwitch.svelte
      ParentsSectionEditor (hierarchical-only),
        DisplayOrderEditor (simple-only) (+ tests + fixtures)
      hierarchical-taxonomy-edit-sections.ts
      hierarchical-taxonomy-edit-types.ts
      simple-taxonomy-edit-sections.ts
      simple-taxonomy-edit-types.ts
    person/
      PersonEditorSwitch.svelte            # promoted from routes/people/[slug]/edit/
      person-edit-sections.ts
    manufacturer/
      ManufacturerEditorSwitch.svelte      # promoted from routes/manufacturers/[slug]/edit/
      manufacturer-edit-sections.ts (+ test)
    corporate-entity/
      CorporateEntityEditorSwitch.svelte   # promoted from routes/corporate-entities/[slug]/edit/
      corporate-entity-edit-sections.ts
    location/
      LocationEditorSwitch.svelte          # promoted from routes/locations/[...path]/edit/
      location-edit-sections.ts
```

**Why per-entity bucketing:** the entity/ split makes "what does Model edit?" one folder-listing away — switch + per-section editors + spec + save are all together. Shared editors live at the root as a small, deliberate set. Cross-checked usage confirms no straddlers — every editor is either used by 2+ entity switches (shared) or by exactly one (per-entity).

**Switch promotions:** all 7 currently-route-private switches (Model, Title, System, Person, Manufacturer, CorporateEntity, Location) move into `editors/entity/X/` alongside the taxonomy switches that were already in `lib`. The previous 2/7 split was incidental, not principled. After the move, every EditorSwitch lives in `editors/`; routes just import them. The cross-route smell that originally promoted ModelEditorSwitch (`titles/[slug]/+layout.svelte` reaching into `../../models/...`) disappears as a side effect.

Add `pages/record/edit/editors/README.md` explaining what makes a file a section editor — the spec / save-claims contract isn't obvious from filenames.

**`pages/record/edit-history/`**

The `/[entity]/[slug]/edit-history/` route across catalog entity types renders only `<EditHistory />`. The component is the page.

- EditHistory + change-display.ts

**`pages/record/sources/`**

The `/[entity]/[slug]/sources/` route across catalog entity types renders only `<EntitySources />`. Same pattern as edit-history.

- EntitySources + entity-sources.ts

**`pages/record/delete/`**

- DeletePage + delete-page.ts

**`pages/listing/`**

- TaxonomyListPage (8 routes)
- GroupedTaxonomyList (technology-generations, display-types)
- NoResultsCreatePrompt — used by TaxonomyListPage + 3 listing routes; reused, so it belongs here. (`CreateFirstModelPrompt` and `CreateFirstCorporateEntityPrompt` are single-route — route-private, see below.)
- PaginatedListPage, CatalogListing, PaginatedListLoader — the SSR paginated-listing controller, its catalog adapter and the loader host. Already created here during the SSR listing work (not moves).

**`pages/error/`**

- ErrorPage

### `entity-links/`

`UserLink` (1 consumer: `ClaimAuthor` in `provenance/`) and `LocationLink` (3 files across `corporate-entities/` and `manufacturers/`) are small route-aware entity links. `ui/` is out (they know about routes). Splitting them — UserLink to `provenance/`, LocationLink somewhere — leaves LocationLink in an awkward single-occupant home given its cross-route use.

Create top-level `entity-links/` as a small family folder for the pair, future-proofing for additional entity links.

```text
entity-links/
  UserLink.svelte
  LocationLink.svelte
```

### `routes/.../_components/`

Components used by only one route family belong next to that route, not in `$lib`. SvelteKit treats directories starting with `_` as non-routable, so `routes/foo/_components/Bar.svelte` is a route-private home that won't accidentally become `/foo/_components`.

**Mechanism:** the candidate list below was derived by running the usage-audit script at `/tmp/audit-component-usage.py` (output at `/tmp/component-usage.md`). The script enumerates every component under `lib/components/`, finds its direct importers, and buckets by route-family count. **Re-run before executing this step** — the codebase will shift (especially once `feat/ssr-titles-faceting` lands) and last session's classifications go stale.

The script has two known limitations to apply manual judgment for:

1. **Transitive multi-route reach.** A single-direct-route component whose only lib consumer is itself multi-route is effectively multi-route. The script only checks one hop; verify manually before committing a move.
2. **Subsystem-coherence override.** Files inside `editors/` are kept together even when an audit shows a single direct route (e.g. `BasicsEditor` only via `ModelEditorSwitch`). The subsystem grouping wins because the editor framework is a coherent unit.

**Root-layout exception:** `routes/+layout.svelte` (the root layout serving every page) is treated as "site-wide," not as a single route family. Components used only by the root layout (`SiteShell`, `MinimalSiteShell`, `FocusSiteShell`) stay in `layout/site/`, not route-private.

**Candidates from the audit:**

- `ThemeSwitcher` → `routes/style-lab/_components/` (only `routes/style-lab/+page.svelte`).
- `TitleFilterSidebar` → `routes/titles/_components/` (only `routes/titles/+page.svelte`). Note: `feat/ssr-titles-faceting` heavily modifies this file — defer this move until after that branch lands.
- `ManufacturerActiveFilterChips` → `routes/manufacturers/_components/` (only `routes/manufacturers/+page.svelte`).

## Potential follow-ups

### Consolidate cross-route test harnesses

`{cabinets,manufacturers,titles}/[slug]/{edit-history,sources,layout}.test-harness.svelte` files import each other across route families — looks like duplicated test setup that wants to live somewhere shared (likely `lib/test/`). Follow-up cleanup, not part of this reorg.

### DRY the manufacturer card grid

`ManufacturerCardGrid` (a `ClientFilteredGrid` + `ManufacturerCard` wrapper) has one importer, but `routes/manufacturers/+page.svelte` hand-rolls the identical block inline instead of using it — a latent second consumer. Blocker: the two call sites expose the manufacturer slug under different field names (`public_id` vs `slug`) from different load shapes, so it's not a clean drop-in. Reconcile the data shape, then promote `ManufacturerCardGrid` to `collections/` and use it on both pages. Behavior-adjacent (touches load shape), so out of scope for the mechanical reorg.
