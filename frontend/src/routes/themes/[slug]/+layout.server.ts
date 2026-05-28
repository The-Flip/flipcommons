import { loadEntityPage } from '$lib/entity-page-loader.server';
import { theme } from '$lib/models';
import { buildEntityJsonLd } from '$lib/models/schema-org';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile } = await loadEntityPage(event, '/api/pages/theme/{public_id}', 'Theme');
  return { profile, jsonLd: buildEntityJsonLd(profile, theme, event.url) };
};
