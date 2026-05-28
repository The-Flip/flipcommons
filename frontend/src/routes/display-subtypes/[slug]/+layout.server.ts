import { loadEntityPage } from '$lib/entity-page-loader.server';
import { displaySubtype } from '$lib/models';
import { buildEntityJsonLd } from '$lib/models/schema-org';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile } = await loadEntityPage(
    event,
    '/api/pages/display-subtype/{public_id}',
    'Display subtype',
  );
  return { profile, jsonLd: buildEntityJsonLd(profile, displaySubtype, event.url) };
};
