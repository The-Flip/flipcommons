import type { TaxonomySchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const tag: EntityInfo<TaxonomySchema> = {
  entityType: 'tag',
  listing: { description: 'Descriptive tags applied to pinball machines.' },
  schemaOrg: { types: ['DefinedTerm'] },
};
