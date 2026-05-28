import type { TaxonomySchema } from '$lib/api/schema';
import type { ModelFrontendInfo } from './types';

export const technologySubgeneration: ModelFrontendInfo<TaxonomySchema> = {
  entityType: 'technology-subgeneration',
  schemaOrg: { types: ['DefinedTerm'] },
};
