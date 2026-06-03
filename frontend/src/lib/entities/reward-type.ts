import type { RewardTypeDetailSchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const rewardType: EntityInfo<RewardTypeDetailSchema> = {
  entityType: 'reward-type',
  listing: { description: 'Types of player rewards offered by pinball machines.' },
  schemaOrg: { types: ['DefinedTerm'] },
};
