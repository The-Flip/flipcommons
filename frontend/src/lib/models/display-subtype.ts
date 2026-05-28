import type { TaxonomySchema } from '$lib/api/schema';
import type { ModelFrontendInfo } from './types';

export const displaySubtype: ModelFrontendInfo<TaxonomySchema> = {
  entityType: 'display-subtype',
  schemaOrg: { types: ['DefinedTerm'] },
};
