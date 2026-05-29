import type { CorporateEntityDetailSchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const corporateEntity: EntityInfo<CorporateEntityDetailSchema> = {
  entityType: 'corporate-entity',
  schemaOrg: {
    types: ['Organization'],
    fieldMap: {
      year_start: { property: 'foundingDate', transform: 'year' },
      year_end: { property: 'dissolutionDate', transform: 'year' },
    },
    relationshipMap: { manufacturer: 'brand' },
  },
  externalRefs: {
    ipdb_manufacturer_id: { identifier: 'IPDB' }, // IPDB has no manufacturer URL
  },
};
