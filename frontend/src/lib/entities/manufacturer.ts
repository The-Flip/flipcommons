import type { ManufacturerDetailSchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

/**
 * Display label for a Title/Model whose manufacturer is unknown. Shown in place
 * of the manufacturer name on title tiles and title/model hero banners so an
 * absent manufacturer reads as "we don't know it" rather than blank — which is
 * ambiguous when several same-named titles appear together (e.g. two "Big Ben").
 */
export const UNKNOWN_MANUFACTURER_LABEL = 'Unknown Manufacturer';

export const manufacturer: EntityInfo<ManufacturerDetailSchema> = {
  entityType: 'manufacturer',
  listing: {
    title: 'Pinball Manufacturers',
    description:
      'Pinball manufacturers and the brands behind them, from the earliest makers to today’s producers.',
  },
  schemaOrg: { types: ['Brand'], fieldMap: { logo_url: 'logo', website: 'url' } },
  externalRefs: {
    opdb_manufacturer_id: { identifier: 'OPDB' },
    wikidata_id: { label: 'Wikidata', urlTemplate: 'https://www.wikidata.org/wiki/{id}' },
  },
};
