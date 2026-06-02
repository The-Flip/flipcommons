import { loadEntityPage } from '$lib/entity-page-loader.server';
import { model } from '$lib/entities';
import { buildEntityJsonLd } from '$lib/entities/schema-org';
import { detailCrumbs } from '$lib/route-metadata.server';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile } = await loadEntityPage(event, '/api/pages/model/{public_id}', 'Machine');

  // Breadcrumb: Home › Titles › Title › Model. There's no /models listing, so
  // the listing crumb comes from the parent Title's entity, not the Model's.
  const crumbs = detailCrumbs('title', {
    label: profile.title.name,
    href: `/titles/${profile.title.public_id}`,
  });

  return { profile, jsonLd: buildEntityJsonLd(profile, model, event.url, crumbs) };
};
