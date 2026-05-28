import type { TaxonomySchema } from '$lib/api/schema';
import type { ModelFrontendInfo } from './types';

export const displayType: ModelFrontendInfo<TaxonomySchema> = {
  entityType: 'display-type',
  schemaOrg: { types: ['DefinedTerm'] },
};
