import type { TaxonomySchema } from '$lib/api/schema';
import type { ModelFrontendInfo } from './types';

export const tag: ModelFrontendInfo<TaxonomySchema> = {
  entityType: 'tag',
  schemaOrg: { types: ['DefinedTerm'] },
};
