import type { ManufacturerDetailSchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

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
