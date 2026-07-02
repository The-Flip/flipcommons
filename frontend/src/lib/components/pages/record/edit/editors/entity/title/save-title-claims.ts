/**
 * Shared save helper for section editors that PATCH title claims.
 */

import { invalidateAll } from '$app/navigation';
import client from '$lib/api/client';
import type { TitleClaimPatchSchema } from '$lib/api/schema';
import { parseApiError } from '$lib/api/parse-api-error';
import type { SaveResult } from '$lib/components/pages/record/edit/editors/save-claims-shared';

type TitleClaimsBody = TitleClaimPatchSchema;

export type TitleSectionPatchBody = Partial<
  Pick<TitleClaimsBody, 'fields' | 'abbreviations' | 'note' | 'citations'>
>;

export async function saveTitleClaims(
  slug: string,
  body: TitleSectionPatchBody,
): Promise<SaveResult> {
  const { error } = await client.PATCH('/api/titles/{public_id}/claims/', {
    params: { path: { public_id: slug } },
    body: { fields: {}, note: '', citations: [], ...body },
  });

  if (error) {
    const parsed = parseApiError(error);
    return { ok: false, error: parsed.message, fieldErrors: parsed.fieldErrors };
  }

  await invalidateAll();
  return { ok: true };
}
