import { loadEntityPage } from '$lib/entity-page-loader.server';
import { tag } from '$lib/models';
import { buildEntityJsonLd } from '$lib/models/schema-org';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile } = await loadEntityPage(event, '/api/pages/tag/{public_id}', 'Tag');
  return { profile, jsonLd: buildEntityJsonLd(profile, tag, event.url) };
};
