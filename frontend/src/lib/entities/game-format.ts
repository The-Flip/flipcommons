import type { TaxonomySchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const gameFormat: EntityInfo<TaxonomySchema> = {
  entityType: 'game-format',
  listing: {
    description: 'Formats of coin-operated amusement games catalogued alongside pinball.',
  },
  schemaOrg: { types: ['DefinedTerm'] },
};
