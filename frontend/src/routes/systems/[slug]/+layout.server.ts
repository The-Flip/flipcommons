import { loadEntityPage } from '$lib/entity-page-loader.server';
import { system } from '$lib/entities';
import { buildEntityJsonLd } from '$lib/entities/schema-org';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile } = await loadEntityPage(event, '/api/pages/system/{public_id}', 'System');
  return { profile, jsonLd: buildEntityJsonLd(profile, system, event.url) };
};
