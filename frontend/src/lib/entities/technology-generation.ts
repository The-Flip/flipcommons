import type { TaxonomySchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const technologyGeneration: EntityInfo<TaxonomySchema> = {
  entityType: 'technology-generation',
  listing: {
    title: 'Pinball Technology Generations',
    description:
      'Generations of pinball technology, from electro-mechanical to solid-state and beyond.',
  },
  schemaOrg: { types: ['DefinedTerm'] },
};
