/**
 * Shared types and helpers used by claims save flows.
 */

import { invalidateAll } from '$app/navigation';
import client from '$lib/api/client';
import { parseApiError, type FieldErrors } from '$lib/api/parse-api-error';
import type {
  ClaimPatchSchema,
  CitationInstanceCreateSchema,
  HierarchyClaimPatchSchema,
  paths,
} from '$lib/api/schema';

/** Metadata that the modal passes through to an editor's save(). */
export type SaveMeta = {
  note?: string;
  citations?: CitationInstanceCreateSchema[];
};

export type SaveResult =
  { ok: true; updatedSlug?: string } | { ok: false; error: string; fieldErrors: FieldErrors };

/**
 * Banner text for a failed save. Field errors the editor renders inline get
 * the generic "fix the errors below" pointer; any key the editor cannot
 * attach to an input surfaces its message verbatim instead — the banner must
 * never swallow a backend message that would otherwise appear nowhere.
 * *claimedKeys* are the fieldErrors keys the editor's inputs look up, built
 * from the same key functions the template renders with so the two can't
 * drift.
 */
export function saveErrorBanner(
  result: Extract<SaveResult, { ok: false }>,
  claimedKeys: Iterable<string>,
): string {
  const claimed = new Set(claimedKeys);
  const orphaned = Object.entries(result.fieldErrors)
    .filter(([key]) => !claimed.has(key))
    .map(([, message]) => message);
  if (orphaned.length > 0) return orphaned.join(' ');
  return Object.keys(result.fieldErrors).length > 0 ? 'Please fix the errors below.' : result.error;
}

type ClaimsBody = ClaimPatchSchema;
type HierarchyClaimsBody = HierarchyClaimPatchSchema;

export type SimpleTaxonomySectionPatchBody = Partial<
  Pick<ClaimsBody, 'fields' | 'note' | 'citations' | 'inline_citations'>
>;

export type HierarchicalTaxonomySectionPatchBody = Partial<
  Pick<
    HierarchyClaimsBody,
    'fields' | 'parents' | 'aliases' | 'note' | 'citations' | 'inline_citations'
  >
>;

/**
 * Any OpenAPI path whose PATCH operation accepts the flat `ClaimPatchSchema`
 * body and identifies the resource by `public_id` (which is the slug for
 * every simple-taxonomy endpoint today). Derived from the schema, so new
 * simple-taxonomy endpoints qualify automatically; hierarchical and
 * entity-specific endpoints (which use richer body schemas) do not.
 */
export type SimpleTaxonomyClaimsPath = {
  [K in keyof paths]: paths[K] extends {
    patch: {
      parameters: { path: { public_id: string } };
      requestBody: { content: { 'application/json': ClaimsBody } };
    };
  }
    ? K
    : never;
}[keyof paths];

/**
 * Save handler for any simple-taxonomy claims endpoint. Callers supply the
 * literal API path so the typed openapi-fetch client can validate it; the body
 * is the flat `ClaimPatchSchema` shape (`fields` / `note` / `citations`).
 */
export async function saveSimpleTaxonomyClaims(
  path: SimpleTaxonomyClaimsPath,
  slug: string,
  body: SimpleTaxonomySectionPatchBody,
): Promise<SaveResult> {
  const { data, error } = await client.PATCH(path, {
    params: { path: { public_id: slug } },
    body: { fields: {}, note: '', citations: [], inline_citations: [], ...body },
  });

  if (error) {
    const parsed = parseApiError(error);
    return { ok: false, error: parsed.message, fieldErrors: parsed.fieldErrors };
  }

  await invalidateAll();
  return { ok: true, updatedSlug: data?.slug ?? slug };
}

/**
 * Any OpenAPI path whose PATCH operation accepts the `HierarchyClaimPatchSchema`
 * body and identifies the resource by `public_id`. Mirrors
 * `SimpleTaxonomyClaimsPath` for hierarchical taxonomies (themes,
 * gameplay-features).
 */
export type HierarchicalTaxonomyClaimsPath = {
  [K in keyof paths]: paths[K] extends {
    patch: {
      parameters: { path: { public_id: string } };
      requestBody: { content: { 'application/json': HierarchyClaimsBody } };
    };
  }
    ? K
    : never;
}[keyof paths];

/**
 * Save handler for any hierarchical-taxonomy claims endpoint.
 */
export async function saveHierarchicalTaxonomyClaims(
  path: HierarchicalTaxonomyClaimsPath,
  slug: string,
  body: HierarchicalTaxonomySectionPatchBody,
): Promise<SaveResult> {
  const { data, error } = await client.PATCH(path, {
    params: { path: { public_id: slug } },
    body: { fields: {}, note: '', citations: [], inline_citations: [], ...body },
  });

  if (error) {
    const parsed = parseApiError(error);
    return { ok: false, error: parsed.message, fieldErrors: parsed.fieldErrors };
  }

  await invalidateAll();
  return { ok: true, updatedSlug: data?.slug ?? slug };
}
