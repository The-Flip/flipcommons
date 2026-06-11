import type { CorporateEntityDetailSchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const corporateEntity: EntityInfo<CorporateEntityDetailSchema> = {
  entityType: 'corporate-entity',
  listing: {
    description:
      'The companies behind pinball brands — the legal entities that designed, manufactured and distributed machines.',
  },
  schemaOrg: {
    types: ['Organization'],
    relationshipMap: { manufacturer: 'brand' },
  },
  externalRefs: {
    ipdb_manufacturer_id: { identifier: 'IPDB' }, // IPDB has no manufacturer URL
  },
};
