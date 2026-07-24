/**
 * Shared logic for presenting a citation source's links, so the tooltip,
 * references list and sources panel all split them the same way.
 */

/** A citation source's link, as sent for display. `display_name` is never
 *  blank — the backend falls it back to the link-type name — so a link is
 *  never rendered as a bare URL. */
export interface CitationLink {
  url: string;
  link_type: string;
  display_name: string;
}

/** A citation's identity fields, shared across the tooltip, sources panel and
 *  edit-history change rows — the input to `CitationBody`. Every citation wire
 *  schema (inline, evidence, field-change) structurally satisfies it. */
export interface CitationIdentity {
  source_name: string;
  /** The parent root's name (e.g. the periodical a cited issue belongs to), so
   *  a child renders in context. Absent/null on a root. */
  root_name?: string | null;
  source_type: string;
  author: string;
  year?: number | null;
  locator: string;
  quote: string;
  links?: CitationLink[];
}

/** The title's href and the remaining links, split from a source's links.
 *  The `reference` link is the source's canonical URL, so it becomes the
 *  hyperlink on the source name rather than a separate chip. */
export interface CitationLinkDisplay {
  /** URL to hyperlink the source name to, or `undefined` for plain text. */
  titleHref: string | undefined;
  /** Links to show as separate chips (everything but the title's link). */
  chips: CitationLink[];
}

export function citationLinkDisplay(links: CitationLink[]): CitationLinkDisplay {
  const reference = links.find((link) => link.link_type === 'reference');
  return {
    titleHref: reference?.url,
    chips: links.filter((link) => link !== reference),
  };
}
