import type { TaxonomySchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const technologySubgeneration: EntityInfo<TaxonomySchema> = {
  entityType: 'technology-subgeneration',
  schemaOrg: { types: ['DefinedTerm'] },
};
