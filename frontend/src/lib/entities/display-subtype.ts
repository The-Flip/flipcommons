import type { DisplaySubtypeDetailPageSchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const displaySubtype: EntityInfo<DisplaySubtypeDetailPageSchema> = {
  entityType: 'display-subtype',
  schemaOrg: { types: ['DefinedTerm'] },
};
