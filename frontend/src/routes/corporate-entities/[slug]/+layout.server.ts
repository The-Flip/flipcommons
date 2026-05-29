import { loadEntityPage } from '$lib/entity-page-loader.server';
import { corporateEntity } from '$lib/entities';
import { buildEntityJsonLd } from '$lib/entities/schema-org';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile } = await loadEntityPage(
    event,
    '/api/pages/corporate-entity/{public_id}',
    'Corporate entity',
  );
  return { profile, jsonLd: buildEntityJsonLd(profile, corporateEntity, event.url) };
};
