import { invalidateAll } from '$app/navigation';
import client from '$lib/api/client';
import type { ClaimPatchSchema } from '$lib/api/schema';
import { parseApiError } from '$lib/api/parse-api-error';
import type {
  SaveMeta,
  SaveResult,
} from '$lib/components/pages/record/edit/editors/save-claims-shared';

export type { SaveMeta, SaveResult };

type PersonClaimsBody = ClaimPatchSchema;

type PersonSectionPatchBody = Partial<
  Pick<PersonClaimsBody, 'fields' | 'note' | 'citations' | 'inline_citations'>
>;

export async function savePersonClaims(
  slug: string,
  body: PersonSectionPatchBody,
): Promise<SaveResult> {
  const { data, error } = await client.PATCH('/api/people/{public_id}/claims/', {
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
