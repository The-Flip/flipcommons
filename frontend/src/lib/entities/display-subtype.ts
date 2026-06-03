import type { DisplaySubtypeDetailSchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const displaySubtype: EntityInfo<DisplaySubtypeDetailSchema> = {
  entityType: 'display-subtype',
  schemaOrg: { types: ['DefinedTerm'] },
};
