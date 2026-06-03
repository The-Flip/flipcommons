import { invalidateAll } from '$app/navigation';
import client from '$lib/api/client';
import type { LocationPatchClaimSchema } from '$lib/api/schema';
import { parseApiError } from '$lib/api/parse-api-error';
import type {
  SaveMeta,
  SaveResult,
} from '$lib/components/pages/record/edit/editors/save-claims-shared';

export type { SaveMeta, SaveResult };

type LocationPatchBody = LocationPatchClaimSchema;

type LocationSectionPatchBody = Partial<
  Pick<LocationPatchBody, 'fields' | 'aliases' | 'divisions' | 'note' | 'citation'>
>;

export async function saveLocationClaims(
  publicId: string,
  body: LocationSectionPatchBody,
): Promise<SaveResult> {
  const { data, error } = await client.PATCH('/api/locations/{public_id}/claims/', {
    params: { path: { public_id: publicId } },
    body: { fields: {}, note: '', ...body },
  });

  if (error) {
    const parsed = parseApiError(error);
    return { ok: false, error: parsed.message, fieldErrors: parsed.fieldErrors };
  }

  await invalidateAll();
  return { ok: true, updatedSlug: data?.public_id ?? publicId };
}
