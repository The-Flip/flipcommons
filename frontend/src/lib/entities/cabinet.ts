import type { TaxonomySchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const cabinet: EntityInfo<TaxonomySchema> = {
  entityType: 'cabinet',
  listing: { description: 'Physical cabinet styles used in pinball machines.' },
  schemaOrg: { types: ['DefinedTerm'] },
};
