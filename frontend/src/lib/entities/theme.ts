import type { ThemeDetailSchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const theme: EntityInfo<ThemeDetailSchema> = {
  entityType: 'theme',
  listing: {
    title: 'Pinball Machine Themes',
    description: 'Themes and subjects depicted across pinball machines.',
  },
  schemaOrg: { types: ['DefinedTerm'], relationshipMap: { parents: 'isPartOf' } },
};
