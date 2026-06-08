import { resolve } from '$app/paths';
import { loadDeletePreview } from '$lib/delete-preview-loader.server';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = ({ fetch, params, url, request }) =>
  loadDeletePreview({
    fetch,
    url,
    request,
    public_id: params.slug,
    entity: 'production-statuses',
    notFoundRedirect: resolve('/production-statuses'),
  });
