import { loadEntityPage } from '$lib/entity-page-loader.server';
import { cabinet } from '$lib/models';
import { buildEntityJsonLd } from '$lib/models/schema-org';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile } = await loadEntityPage(event, '/api/pages/cabinet/{public_id}', 'Cabinet');
  return { profile, jsonLd: buildEntityJsonLd(profile, cabinet, event.url) };
};
