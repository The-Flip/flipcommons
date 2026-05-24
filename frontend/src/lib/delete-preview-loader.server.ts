import { redirect } from '@sveltejs/kit';
import { createServerClient } from '$lib/api/server';
import { requireCapability } from '$lib/require-capability.server';
import type { paths } from '$lib/api/schema';

// Entity-segment union derived from the schema's delete-preview routes.
// New linkable entities pick this up automatically when api-gen runs.
type DeletePreviewEntity =
  Extract<
    keyof paths,
    `/api/${string}/{public_id}/delete-preview/`
  > extends `/api/${infer E}/{public_id}/delete-preview/`
    ? E
    : never;

type DeletePreviewResponse<E extends DeletePreviewEntity> =
  paths[`/api/${E}/{public_id}/delete-preview/`] extends {
    get: { responses: { 200: { content: { 'application/json': infer R } } } };
  }
    ? R
    : never;

interface DeletePreviewLoadOptions<E extends DeletePreviewEntity> {
  fetch: typeof fetch;
  url: URL;
  // Required: forwarded to createServerClient for cookie forwarding.
  // Dropping this would re-introduce #420 (anonymous /me/ during SSR).
  request: Request;
  public_id: string;
  entity: E;
  notFoundRedirect: string;
}

export async function loadDeletePreview<E extends DeletePreviewEntity>({
  fetch,
  url,
  request,
  public_id,
  entity,
  notFoundRedirect,
}: DeletePreviewLoadOptions<E>): Promise<{
  preview: DeletePreviewResponse<E>;
  public_id: string;
}> {
  const endpoint = `/api/${entity}/{public_id}/delete-preview/`;

  await requireCapability({ fetch, url, request, activity: 'catalog.delete' });

  const client = createServerClient(fetch, url, request);

  // openapi-fetch can't resolve a typed response for a path it sees as a
  // dynamic string, so the casts are localized here. `entity` is already
  // statically constrained to DeletePreviewEntity at the call site.
  const {
    data,
    error: preverr,
    response,
  } = await client.GET(
    endpoint as never,
    {
      params: { path: { public_id } },
    } as never,
  );
  const status = response.status;
  if (status === 404) {
    throw redirect(302, notFoundRedirect);
  }
  if (preverr || !data) {
    throw new Error(`Failed to load delete preview (${status})`);
  }

  return { preview: data as DeletePreviewResponse<E>, public_id };
}
