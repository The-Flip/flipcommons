import type { ThemeDetailSchema } from '$lib/api/schema';
import type { ModelFrontendInfo } from './types';

export const theme: ModelFrontendInfo<ThemeDetailSchema> = {
  entityType: 'theme',
  schemaOrg: { types: ['DefinedTerm'] },
};
