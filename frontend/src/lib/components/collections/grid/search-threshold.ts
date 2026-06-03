/**
 * Minimum item count at which list pages render a search input. Below this,
 * the full list is visible on screen and search is neither needed nor useful.
 *
 * Shared so that the list-page create affordance (header "+ New X" link vs
 * no-results create prompt) gates on the exact same threshold as the search
 * input itself — duplicating the number would let the two drift.
 */
export const SEARCH_THRESHOLD = 12;
