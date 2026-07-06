# Frontend Testing

Frontend tests use `vitest`.

## What to Test

- TypeScript module logic
- component behavior where UI wiring matters
- data-shape expectations against the API contract where appropriate

Split pure logic out of Svelte components into plain TypeScript modules so it can be tested without a DOM environment. Those unit tests go in `*.test.ts` files (not `*.dom.test.ts`), which run in Node.

Prefer TDD — write the test before the implementation — when it clarifies the problem or the interface. Skip it when the test would be awkward to write before the code exists (e.g. exploratory UI work).

## Test Tiers

The frontend has two vitest **projects** (configured in `vitest.config.ts`) that run in different environments:

| Project | Environment | File pattern    | What to test                                                |
| ------- | ----------- | --------------- | ----------------------------------------------------------- |
| `unit`  | Node        | `*.test.ts`     | Pure functions, SSR renders (`svelte/server`), data helpers |
| `dom`   | jsdom       | `*.dom.test.ts` | Component interactions, event handling, DOM behavior        |

Both run together via `pnpm test`. For focused iteration:

```bash
pnpm test:unit        # unit tests only
pnpm test:dom         # DOM tests only
pnpm test:dom:watch   # DOM tests in watch mode
```

## Creating a DOM Test

Name the file `*.dom.test.ts` next to the component. The `.dom.` suffix routes it to the jsdom project automatically. Use `@testing-library/svelte` for rendering and queries, `userEvent` for interactions. See `wikilink-autocomplete.dom.test.ts` for the canonical example of mocking standalone API functions, and `markdown-textarea-citation.dom.test.ts` for mocking the openapi-fetch typed client.

**Gotcha:** when calling exported component methods directly (e.g. `handleExternalKeydown`), wrap in `flushSync` from `svelte` — DOM updates from direct method calls are not automatically flushed.

### jsdom Polyfills

The DOM project loads `src/tests/setup-dom.ts` which provides:

- `@testing-library/jest-dom/vitest` — DOM matchers (`toBeInTheDocument()`, `toHaveTextContent()`, etc.)
- `Element.prototype.scrollIntoView` — no-op (jsdom doesn't implement it)
- `document.execCommand` — returns `false` (triggers manual text insertion fallbacks)

## DOM Test Patterns

These patterns are established in the wikilink autocomplete tests. Follow them when adding new DOM tests.

### Shared mock data

When multiple test files mock the same API module, extract the data to a shared fixtures file rather than duplicating it. Vitest's `vi.mock` factories are hoisted above imports, so they can't reference regular imports. Use an async factory with dynamic import:

```typescript
import { SEARCH_RESULTS } from "./link-types-fixtures";

vi.mock("$lib/api/link-types", async () => {
  const f = await import("./link-types-fixtures");
  return {
    fetchLinkTypes: vi.fn().mockResolvedValue(f.LINK_TYPES),
    searchLinkTargets: vi.fn().mockResolvedValue({ results: f.SEARCH_RESULTS }),
  };
});
```

Import the data directly (non-hoisted) for use in test assertions.

### Mock reset between tests

Use `mockReset().mockResolvedValue(...)` in `beforeEach`, not `mockClear()`. `mockClear` only clears call history — `mockResolvedValueOnce` overrides persist across tests unless the implementation is explicitly reset. Prefer `beforeEach` over `afterEach` — it guarantees the first test in a suite has defaults configured, regardless of whether the `vi.mock` factory provides them.

### Layered flow helpers

Extract multi-step setup into composable helpers that build on each other: `waitForTypes()` → `openSearch()` → select result. Individual tests stay short and focused on one assertion.

### Fixture wrappers for real context

When a component needs a real parent context — for example `bind:` state, snippet props, or a concrete DOM container element — prefer a tiny fixture component over mocking the component's internals. Keep the fixture minimal and let the DOM test drive the real surface area.

### Synchronous vs. async assertions

Only wait when the production code actually defers work. If the code path under test is synchronous (e.g. `handleInput` → `detectTrigger` for a single `[`), assert immediately — don't add `waitFor`, fake timers, or sleeps. Unnecessary waits teach the wrong pattern and hide whether the code is actually async.

### Test at the right layer

Timing mechanics (exact debounce delay, coalescing behavior, generation counters) belong in unit tests for the helper module. DOM tests should verify UI-visible outcomes: "typing updates results" and "stale response doesn't win." Over-coupling DOM tests to helper internals makes them fragile and duplicates coverage.

For consumer wiring tests, prove that the parent surface updates, resets, or routes events correctly. Do not re-test the full interaction matrix of a shared child component if that child already has its own exemplar DOM suite.

### Querying elements

Use accessible roles and names (`getByRole('combobox', { name: /search title/i })`) rather than CSS classes or test IDs. Tests survive refactors that change DOM structure as long as semantics are preserved.

If a control has visible label text but no accessible name, prefer fixing the component so the test can keep using semantic queries instead of normalizing placeholder- or class-based lookups.

### Mocking browser constructors

When a component creates browser APIs with `new` (for example `IntersectionObserver`), mock them with a constructor-shaped class or function that behaves like the real API surface. A plain object-returning stub is not enough when production code instantiates the global.

### Mocking the openapi-fetch client

Components that use `client.GET`/`client.POST` from `$lib/api/client` need the default export mocked as an object with method stubs. Use `vi.hoisted` to create the mock functions before `vi.mock` hoisting — this avoids type-casting issues with openapi-fetch's deep generic signatures:

```typescript
const { mockGET, mockPOST } = vi.hoisted(() => ({
  mockGET: vi.fn(),
  mockPOST: vi.fn(),
}));

vi.mock("$lib/api/client", () => ({
  default: { GET: mockGET, POST: mockPOST },
}));
```

Set default responses in `beforeEach` with `mockReset()`:

```typescript
beforeEach(() => {
  mockGET.mockReset().mockResolvedValue({ data: DEFAULT_DATA });
  mockPOST.mockReset();
});
```

When `POST` serves multiple endpoints (e.g. `/api/citation-sources/` and `/api/citation-instances/reservations/`), `mockResolvedValueOnce` is consumed in call order, not by path. Set the mock immediately before the action that triggers the call so the pairing is obvious:

```typescript
mockPOST.mockResolvedValueOnce({ data: { id: 42 } });
await user.keyboard("{Enter}"); // triggers the POST
```

When a test flow hits multiple `GET` endpoints (search, detail, children), use `mockImplementation` with URL dispatch instead of chaining `mockResolvedValueOnce` calls. The URL is the first argument to `client.GET`:

```typescript
mockGET.mockImplementation((url: string) => {
  if (url === "/api/citation-sources/search/") {
    return Promise.resolve({ data: SEARCH_RESULTS });
  }
  if (url === "/api/citation-sources/{source_id}/") {
    return Promise.resolve({ data: DETAIL_RESPONSE });
  }
  return Promise.resolve({ data: [] });
});
```

This is clearer than sequential `mockResolvedValueOnce` when the call order depends on async timing or user interaction paths.

See `markdown-textarea-citation.dom.test.ts` for the canonical example.

### `onpointerdown` handlers and `fireEvent.pointerDown`

Several dropdown components use `onpointerdown` with `e.preventDefault()` to handle clicks without stealing focus from the active input. `user.click()` fires `pointerdown` → `mousedown` → `focus` → `click`, which fights the `preventDefault()`. Use `fireEvent.pointerDown()` instead — it fires only the pointer event, matching the component's handler:

```typescript
fireEvent.pointerDown(screen.getByRole("button", { name: /skip/i }));
```

This applies to DropdownItem, DropdownHeader's back button, type chips, and any similar handler that calls `e.preventDefault()` on `pointerdown`.

### userEvent `[` workaround

`userEvent` treats `[` as a key-descriptor opener (`[[` = escape for a single literal `[`). For typing `[[` into a textarea, set the value directly and fire `fireEvent.input()` rather than fighting the parser. Document the workaround with a comment explaining why.
