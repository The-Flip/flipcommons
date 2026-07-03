/**
 * The frontend half of the citation-type plugin contract.
 *
 * A citation type's declarative facts (label, locator kind, placeholder,
 * error message) arrive via the generated `citation-type-meta.ts`; this
 * interface carries the *behavior* a type may need on the client — currently
 * just the locator grammar mirror for inline validation UX. The backend
 * grammar stays authoritative on every write path.
 *
 * Schemes (youtube, ipdb, …) have no frontend footprint at all: recognition,
 * identifier handling and deep-link building all run server-side, and the
 * frontend renders the URLs it is given.
 */
export interface CitationTypeFrontend {
  /**
   * Validate and canonicalize a non-empty locator input, or return null when
   * it doesn't fit the type's grammar. Freeform types return the input
   * unchanged; empty input never reaches this (a locator is optional on
   * every type).
   */
  normalizeLocator(raw: string): string | null;
}

/** The freeform behavior shared by every type without a locator grammar. */
export const freeformType: CitationTypeFrontend = {
  normalizeLocator(raw: string): string {
    return raw;
  },
};
