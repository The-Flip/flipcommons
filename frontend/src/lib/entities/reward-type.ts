import type { RewardTypeDetailSchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const rewardType: EntityInfo<RewardTypeDetailSchema> = {
  entityType: 'reward-type',
  schemaOrg: { types: ['DefinedTerm'] },
};
