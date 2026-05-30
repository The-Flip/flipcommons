import type { TaxonomySchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const displaySubtype: EntityInfo<TaxonomySchema> = {
  entityType: 'display-subtype',
  schemaOrg: { types: ['DefinedTerm'] },
};
