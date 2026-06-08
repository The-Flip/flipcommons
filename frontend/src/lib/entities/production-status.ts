import type { TaxonomySchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const productionStatus: EntityInfo<TaxonomySchema> = {
  entityType: 'production-status',
  listing: {
    description:
      'Status in regards to commercial production, such as whether it has been commercially produced, announced, or is a one-off never intended to be produced.',
  },
  schemaOrg: { types: ['DefinedTerm'] },
};
