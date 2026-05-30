import type { TaxonomySchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const tag: EntityInfo<TaxonomySchema> = {
  entityType: 'tag',
  schemaOrg: { types: ['DefinedTerm'] },
};
