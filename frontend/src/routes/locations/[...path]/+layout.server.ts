import { error } from '@sveltejs/kit';
import { createServerClient } from '$lib/api/server';
import { location } from '$lib/entities';
import { buildEntityJsonLd } from '$lib/entities/schema-org';
import type { Crumb } from '$lib/components/jsonld';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async ({ fetch, url, request, params }) => {
  const path = params.path ?? '';
  const client = createServerClient(fetch, url, request);

  // The global root (`path === ''`) is a listing shell, not an entity — it
  // emits no JSON-LD. Handled in its own branch so the concrete-location
  // branch below keeps the narrowed detail type (with `ancestors`).
  if (path === '') {
    const result = await client.GET('/api/pages/locations/', {});
    if (!result.data) {
      throw error(result.response?.status || 500, 'Failed to load location');
    }
    return { profile: result.data };
  }

  const result = await client.GET('/api/pages/locations/{location_path}', {
    params: { path: { location_path: path } },
  });
  if (!result.data) {
    if (result.response?.status === 404) throw error(404, 'Location not found');
    throw error(result.response?.status || 500, 'Failed to load location');
  }
  const profile = result.data;

  // Breadcrumb: Home › ⟨ancestor chain⟩ › self. Ancestor location pages are
  // SSR, so the whole chain is crawlable.
  const crumbs: Crumb[] = [
    { label: 'Home', href: '/' },
    ...profile.ancestors.map((a) => ({ label: a.name, href: `/locations/${a.public_id}` })),
  ];

  return { profile, jsonLd: buildEntityJsonLd(profile, location, url, crumbs) };
};
