import type { TaxonomySchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const gameFormat: EntityInfo<TaxonomySchema> = {
  entityType: 'game-format',
  schemaOrg: { types: ['DefinedTerm'] },
};
