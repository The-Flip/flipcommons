import type { TaxonomySchema } from '$lib/api/schema';
import type { ModelFrontendInfo } from './types';

export const technologyGeneration: ModelFrontendInfo<TaxonomySchema> = {
  entityType: 'technology-generation',
  schemaOrg: { types: ['DefinedTerm'] },
};
