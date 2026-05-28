import type { TaxonomySchema } from '$lib/api/schema';
import type { ModelFrontendInfo } from './types';

export const cabinet: ModelFrontendInfo<TaxonomySchema> = {
  entityType: 'cabinet',
  schemaOrg: { types: ['DefinedTerm'] },
};
