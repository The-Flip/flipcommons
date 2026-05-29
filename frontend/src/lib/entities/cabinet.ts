import type { TaxonomySchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const cabinet: EntityInfo<TaxonomySchema> = {
  entityType: 'cabinet',
  schemaOrg: { types: ['DefinedTerm'] },
};
