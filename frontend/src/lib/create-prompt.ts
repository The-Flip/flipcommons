/**
 * Gating logic for the "Create?" prompt on the catalog list pages (titles,
 * manufacturers — entity-agnostic).
 *
 * The prompt is driven by the server's **query-only count** — the number of
 * entities matching `q` alone, ignoring any active facets. That distinction
 * matters: the filtered card `count` can be zero merely because a facet is
 * hiding an existing entity (filter to Williams, search a Stern title), and
 * offering to create it there would produce a duplicate. `queryCount === 0`
 * means the name is genuinely free, so the prompt is correct even under active
 * facets.
 *
 * `queryCount` rides the streamed facets payload, so it is `undefined` until
 * that resolves (or if it errors) — we never flash a "create" offer on missing
 * data.
 *
 * Extracted so we can unit-test these invariants.
 */

export interface CreatePromptInputs {
  /** The active `q` search term. */
  query: string;
  isAuthenticated: boolean;
  /**
   * Entities matching `q` alone, ignoring active facets; `null` when there is no
   * `q`, `undefined` while the streamed facets payload is still pending.
   */
  queryCount: number | null | undefined;
}

export interface CreatePromptDecision {
  show: boolean;
  query: string;
}

export function decideCreatePrompt(inputs: CreatePromptInputs): CreatePromptDecision {
  const q = inputs.query.trim();
  if (!q) return { show: false, query: '' };
  if (!inputs.isAuthenticated) return { show: false, query: q };
  return { show: inputs.queryCount === 0, query: q };
}
