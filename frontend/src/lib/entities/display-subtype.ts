import type { DisplaySubtypePageSchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const displaySubtype: EntityInfo<DisplaySubtypePageSchema> = {
  entityType: 'display-subtype',
  schemaOrg: { types: ['DefinedTerm'] },
};
