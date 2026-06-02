import { loadEntityPage } from '$lib/entity-page-loader.server';
import { corporateEntity } from '$lib/entities';
import { buildEntityJsonLd } from '$lib/entities/schema-org';
import { detailCrumbs } from '$lib/route-metadata.server';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async (event) => {
  const { profile } = await loadEntityPage(
    event,
    '/api/pages/corporate-entity/{public_id}',
    'Corporate entity',
  );

  // Breadcrumb: Home › Manufacturers › Manufacturer › Corporate entity. A CE
  // reads as nested under its manufacturer, so the trail anchors on the
  // manufacturer's listing rather than a /corporate-entities crumb.
  const crumbs = detailCrumbs('manufacturer', {
    label: profile.manufacturer.name,
    href: `/manufacturers/${profile.manufacturer.public_id}`,
  });

  return { profile, jsonLd: buildEntityJsonLd(profile, corporateEntity, event.url, crumbs) };
};
