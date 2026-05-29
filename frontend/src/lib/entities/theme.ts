import type { ThemeDetailSchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const theme: EntityInfo<ThemeDetailSchema> = {
  entityType: 'theme',
  schemaOrg: { types: ['DefinedTerm'] },
};
