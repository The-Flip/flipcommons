import { error } from '@sveltejs/kit';
import { createServerClient } from '$lib/api/server';
import { cabinet } from '$lib/models';
import { buildEntityJsonLd } from '$lib/models/schema-org';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async ({ fetch, url, request, params }) => {
  const client = createServerClient(fetch, url, request);
  const { data, response } = await client.GET('/api/pages/cabinet/{public_id}', {
    params: { path: { public_id: params.slug } },
  });

  if (!data) {
    if (response?.status === 404) throw error(404, 'Cabinet not found');
    throw error(response.status || 500, 'Failed to load page');
  }

  return { profile: data, jsonLd: buildEntityJsonLd(data, cabinet, url) };
};
