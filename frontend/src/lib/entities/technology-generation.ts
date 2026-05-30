import type { TaxonomySchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const technologyGeneration: EntityInfo<TaxonomySchema> = {
  entityType: 'technology-generation',
  schemaOrg: { types: ['DefinedTerm'] },
};
