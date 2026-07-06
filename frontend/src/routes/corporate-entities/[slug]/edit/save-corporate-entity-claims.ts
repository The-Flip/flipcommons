import { invalidateAll } from '$app/navigation';
import client from '$lib/api/client';
import type { CorporateEntityClaimPatchSchema } from '$lib/api/schema';
import { parseApiError } from '$lib/api/parse-api-error';
import type { SaveResult } from '$lib/components/pages/record/edit/editors/save-claims-shared';

export type { SaveResult };

type CorporateEntityClaimsBody = CorporateEntityClaimPatchSchema;

type CorporateEntitySectionPatchBody = Partial<
  Pick<CorporateEntityClaimsBody, 'fields' | 'aliases' | 'note' | 'citations' | 'inline_citations'>
>;

export async function saveCorporateEntityClaims(
  slug: string,
  body: CorporateEntitySectionPatchBody,
): Promise<SaveResult> {
  const { data, error } = await client.PATCH('/api/corporate-entities/{public_id}/claims/', {
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
