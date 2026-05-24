# Route Metadata and Walking

Plan for introducing route-metadata primitives — `frontend/src/lib/route-metadata.ts` — and the first piece of metadata that lives there: a per-route `searchEngineInclusion` classification, plus walker utilities and tests that enforce it.

The route-metadata primitive is consumed by the SEO strategy (see [`SearchEngines.md`](SearchEngines.md)), but is independently valuable as an auth-gating enforcement test — it pays off even if no SEO work ever happens.

## Why

Two unrelated-looking problems share a root cause: there's no machine-readable answer for "what kind of route is this?"

1. **Search-engine inclusion is implicit.** Is `/search` supposed to be in Google's index? `/style-lab`? `/login`? Today the answers live in reviewer attention and conventions. A new route silently inherits "yes" by default; if you forgot to think about it, the sitemap ships it.
2. **Auth gating is declared, but nothing enforces "is the right mechanism used?"** `requireCapability` is the canonical helper, but nothing stops someone from rolling a one-off `if (!locals.user) throw redirect(...)` inside `+page.server.ts`. The mistake is invisible until a security audit.

Making the search-engine signal explicit on every route — and adding a test that cross-checks the auth mechanism against the layout chain — closes both gaps with one small piece of machinery. This work is independently valuable: the auth-mechanism enforcement is a security guardrail that pays off even if no SEO work ever happens. (The follow-on work in [`Robots.md`](Robots.md) and [`Sitemap.md`](Sitemap.md) consumes it as a dependency.)

The file is named `route-metadata.ts` because we'll likely add more per-route metadata over time (canonical tags, SSR overrides, custom analytics flags, etc.); the search-engine classification is just the first.

## The two orthogonal signals

Each piece of information lives in exactly one place — no parallel systems, no redundant declarations.

- **`requireCapability` in a `+layout.server.ts`** = the route is gated. This is what the codebase already uses today; nothing changes about the auth mechanism itself. The walker reads this to determine that a route is auth-gated.
- **`export const searchEngineInclusion` on a route or layout file** = whether the route should appear in search-engine indexes. Two values: `'included'` or `'excluded'`. Layouts let descendants inherit.

The two axes are independent at the declaration layer. Consumers (sitemap, robots.txt) compose them via the `isIndexable()` predicate, which returns `true` only when the route is included AND not gated.

## The `SearchEngineInclusion` type

```ts
// frontend/src/lib/route-metadata.ts
export type SearchEngineInclusion = "included" | "excluded";

export const SEARCH_ENGINE_INCLUSION_VALUES = ["included", "excluded"] as const;
```

## Where the `searchEngineInclusion` exports go

Inheritance does most of the work. Set the default at the top-level layout:

```ts
// frontend/src/routes/+layout.ts
export const searchEngineInclusion = "included" as const;
```

Override at leaves where they differ:

```ts
// frontend/src/routes/login/+page.server.ts
export const searchEngineInclusion = "excluded" as const;
```

```ts
// frontend/src/routes/style-lab/+page.ts
export const searchEngineInclusion = "excluded" as const;
```

Routes that today only have `+page.svelte` need a `+page.ts` added to carry the export. Trivial — one-line file.

**Gated routes don't need this export.** Routes under a `requireCapability` layout (today: `/a/*`; catalog edit subroutes once they have such a layout) are inherently excluded from search engines — there's no point declaring `searchEngineInclusion = 'excluded'` on them. The walker treats them as excluded by virtue of being auth-gated. Declaring it anyway would be a contradiction the test catches (see below).

For catalog edit subroutes (`/titles/[slug]/edit`, `/sources`, `/edit-history`, `/new`), the path forward is to put `requireCapability` on the section's `+layout.server.ts` (or add one). Once that layout exists, the entire subtree is auth-gated — no per-route `searchEngineInclusion` declaration needed anywhere in it.

## Walker primitives

`frontend/src/lib/route-metadata.ts` exposes composable utilities the test and downstream consumers all share:

```ts
export function allRoutes(): RouteId[];
export function searchEngineInclusionFor(id: RouteId): SearchEngineInclusion;
export function isAuthGated(id: RouteId): boolean; // via requireCapability ancestor
export function isIndexable(id: RouteId): boolean; // composite: !isAuthGated && included
export function layoutChain(id: RouteId): string[]; // ancestor +layout(.server)?.ts paths
export function hasAncestorImport(id: RouteId, module: string): boolean;
```

`isIndexable()` is the composite predicate consumers actually want:

```ts
export function isIndexable(id: RouteId): boolean {
  if (isAuthGated(id)) return false;
  return searchEngineInclusionFor(id) === "included";
}
```

Internally the walker wraps `import.meta.glob('/src/routes/**/+*')`. Roughly 100 lines.

## The test (`route-metadata.test.ts`)

A route is well-formed iff **exactly one** of these is true:

1. It has a `requireCapability` ancestor (auth-gated). No `searchEngineInclusion` export anywhere in its chain.
2. It has a `searchEngineInclusion` export (one of `SEARCH_ENGINE_INCLUSION_VALUES`) somewhere in its chain. No `requireCapability` ancestor.

The test enumerates `allRoutes()` and asserts each route falls cleanly into one of the two cases. Two failure modes:

- **Both signals present** → contradiction. "You declared `searchEngineInclusion` on a route that's auth-gated. Auth-gated routes are inherently excluded; drop the declaration."
- **Neither signal present** → unclassified. "Either gate this route via `requireCapability` or declare its `searchEngineInclusion`."

Bi-directional auth-mechanism enforcement falls out of this naturally. The same layout-chain inspection that determines `isAuthGated()` IS the auth gate, so they can't drift. A one-off `if (!locals.user) throw redirect(...)` in some `+page.server.ts` won't register as an auth gate — that route will fail the test as "unclassified" until either `requireCapability` is added or a `searchEngineInclusion` export is declared.

**Anchor sanity check.** A small set of known-stable routes (`/`, `/titles`, `/titles/[slug]`, `/about`, `/login`, `/a/dashboard`) must appear in `allRoutes()` and resolve to the expected combination of `searchEngineInclusionFor()` / `isAuthGated()` values. Defends against "walker silently returned nothing, so all assertions trivially pass." Self-documenting; a magic-number count threshold would catch the same case less precisely and would rot on intentional route consolidation.

Implementation note for the auth detection: static text-match scan of `+layout.server.ts` files for the `require-capability.server` import. Cheap and adequate at current size. If a future second auth mechanism is introduced, this is the canonical place to recognize it — updating the walker is a deliberate decision rather than a silent broadening.

## Refactor existing route-walking

One existing test walks the route tree for an adjacent purpose and should consume the walker:

- **`frontend/src/lib/api/catalog-meta.test.ts`** uses `import.meta.glob('/src/routes/**/+*')` to discover detail routes and assert each is mapped in `CATALOG_META`. Refactor to consume `allRoutes()` (and a helper that recognizes catalog-detail patterns). One walker, one set of bugs.

Out of scope — don't refactor these:

- **`frontend/src/lib/focus-mode.ts`** (`MINIMAL_SHELL_EXACT_PATHS`, `FOCUS_EXACT_PATHS`, `isFocusModePath()`) classify routes by UI chrome, a different axis. Some paths overlap (`/signup`, `/auth/error`, `/kiosk`, `*/edit` suffixes) but binding two axes together when they happen to overlap creates a future "they diverged" headache. Revisit only if they actually drift.
- **`frontend/src/lib/frontDoors.ts`** is a UI-shell concern; unrelated.

## What this enables downstream

- **`robots.txt`** — see [`Robots.md`](Robots.md). Derives `Disallow:` lines from `isIndexable()` over the route tree.
- **`sitemap.xml`** — see [`Sitemap.md`](Sitemap.md). Feeds `isIndexable()` into super-sitemap's `excludeRoutePatterns`.
- **Future per-route metadata** — the same file (`route-metadata.ts`) is the natural home for additional per-route signals (canonical URL overrides, SSR exceptions, analytics tags, etc.). Same walker primitives, new exports.
- **Future cross-cutting tests** — e.g. "every catalog detail route has an `edit-history` and `sources` subroute," "every included route renders a `<link rel='canonical'>`." Reusable walker, ad-hoc composition.

## Implementation order

1. Write `frontend/src/lib/route-metadata.ts`: the `SearchEngineInclusion` type, walker primitives (`allRoutes`, `searchEngineInclusionFor`, `layoutChain`, `hasAncestorImport`), and `isIndexable` / `isAuthGated` predicates.
2. Add `export const searchEngineInclusion` to route files for the non-gated routes only. Top-level `+layout.ts` defaults to `'included'`; non-indexable routes (`/login`, `/signup`, `/verify-email`, `/auth/error`, `/search`, `/kiosk`, `/api-docs`, `/style-lab`, `/_sentry_test`) override to `'excluded'`. Gated routes get nothing — `requireCapability` already declares them. Add `+page.ts` files where they don't exist yet.
3. Add the route-metadata vitest test: every route is well-formed (exactly one of "gated" or "declares `searchEngineInclusion`"); anchor sanity. It'll initially fail until the exports are filled in — that's the point.
4. Refactor `frontend/src/lib/api/catalog-meta.test.ts` to consume the walker (`allRoutes()` + a catalog-detail predicate) instead of doing its own `import.meta.glob` traversal.
5. Open PR. The follow-on SEO work in [`Robots.md`](Robots.md) (first) and [`Sitemap.md`](Sitemap.md) (second) can be opened as drafts on top of this branch.
