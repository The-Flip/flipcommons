import type { GameplayFeatureDetailSchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const gameplayFeature: EntityInfo<GameplayFeatureDetailSchema> = {
  entityType: 'gameplay-feature',
  listing: {
    title: 'Pinball Machine Gameplay Features',
    description: 'Mechanical and digital features that define how a game plays.',
  },
  schemaOrg: { types: ['DefinedTerm'], relationshipMap: { parents: 'isPartOf' } },
};
