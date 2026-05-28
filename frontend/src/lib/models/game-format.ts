import type { TaxonomySchema } from '$lib/api/schema';
import type { ModelFrontendInfo } from './types';

export const gameFormat: ModelFrontendInfo<TaxonomySchema> = {
  entityType: 'game-format',
  schemaOrg: { types: ['DefinedTerm'] },
};
