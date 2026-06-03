import type { TaxonomySchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const displayType: EntityInfo<TaxonomySchema> = {
  entityType: 'display-type',
  listing: {
    title: 'Pinball Machine Display Types',
    description: 'Display technologies used to show scores and animations on pinball machines.',
  },
  schemaOrg: { types: ['DefinedTerm'] },
};
