/** The draft rule shared by every search box that commits `?q=` to the URL. */

/** Handle onto a live search draft; bind a `SearchBox` to `value`. */
export interface SearchDraft {
  /** The live input value, ahead of the committed query while the user types. */
  value: string;
  /**
   * Record a query committed by something other than this draft — e.g. a filter
   * control that navigates while preserving the current `q` — so that
   * navigation's landing is recognized as ours instead of replacing the draft.
   */
  markCommitted: (next: string) => void;
}

/** Quiet period before a draft commits. Shared by every search box so the commit
 * rhythm is uniform: a box that commits at its own pace reads as a glitch. */
const COMMIT_DELAY_MS = 250;

/**
 * Debounced draft state for a search box whose committed query round-trips
 * through the URL.
 *
 * The draft is its own state rather than a projection of the committed query:
 * that value changes when a navigation lands, which is exactly when a
 * still-typing user is ahead of it, so projecting it would rewind the box
 * mid-word. A landing we caused is recognized by identity — committing records
 * what it sent — and leaves the draft alone; a query arriving from outside
 * (back/forward, a link to the same route) is the user asking for a specific
 * state, so it replaces the draft and abandons any commit that draft had
 * scheduled.
 *
 * Call during component init: it owns two `$effect`s.
 *
 * @param committed Reads the currently committed query, normally an SSR-load prop.
 * @param commit Publishes a new query, normally a `goto` of the same route.
 */
export function searchDraft(committed: () => string, commit: (next: string) => void): SearchDraft {
  let draft = $state(committed());
  let lastCommitted = committed();

  $effect(() => {
    const next = committed();
    if (next === lastCommitted) return;
    lastCommitted = next;
    draft = next;
  });

  let timer: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    const next = draft.trim();
    if (next === committed()) return;
    clearTimeout(timer);
    timer = setTimeout(() => {
      lastCommitted = next;
      commit(next);
    }, COMMIT_DELAY_MS);
    return () => clearTimeout(timer);
  });

  return {
    get value() {
      return draft;
    },
    set value(next: string) {
      draft = next;
    },
    markCommitted(next: string) {
      lastCommitted = next;
    },
  };
}
