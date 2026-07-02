import type { CitationInstanceCreateSchema } from '$lib/api/schema';

/** A citation the user attached to an edit: the content spec the save payload
 * sends (source + locator + quote — the backend mints the shared instance at
 * save time) plus the source name for display. */
export type EditCitationSelection = {
  citationSourceId: number;
  sourceName: string;
  locator: string;
  quote: string;
};

type PatchBody = Record<string, unknown>;

/** Build the save payload's `citations` list from the user's selection
 * (empty when no citation was attached). */
export function buildEditCitationsRequest(
  citation: EditCitationSelection | null,
): CitationInstanceCreateSchema[] {
  if (!citation) return [];
  return [
    {
      citation_source_id: citation.citationSourceId,
      locator: citation.locator,
      quote: citation.quote,
    },
  ];
}

export function withEditMetadata<T extends PatchBody>(
  body: T,
  note: string,
  citation: EditCitationSelection | null,
): T & { note: string; citations: CitationInstanceCreateSchema[] } {
  return {
    ...body,
    note: note.trim(),
    citations: buildEditCitationsRequest(citation),
  };
}

export function countPendingChanges(body: PatchBody | null): number {
  if (!body) return 0;

  let count = 0;
  for (const [key, value] of Object.entries(body)) {
    if (key === 'note' || key === 'citations' || value == null) continue;

    if (key === 'fields' && typeof value === 'object' && !Array.isArray(value)) {
      count += Object.keys(value as Record<string, unknown>).length;
      continue;
    }

    count += 1;
  }

  return count;
}

export function shouldShowMixedEditCitationWarning(
  body: PatchBody | null,
  citation: EditCitationSelection | null,
): boolean {
  return citation !== null && countPendingChanges(body) > 1;
}
