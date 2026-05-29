import type { TaxonomySchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const displayType: EntityInfo<TaxonomySchema> = {
  entityType: 'display-type',
  schemaOrg: { types: ['DefinedTerm'] },
};
