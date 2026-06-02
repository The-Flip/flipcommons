import type { FranchiseDetailSchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const franchise: EntityInfo<FranchiseDetailSchema> = {
  entityType: 'franchise',
  listing: { description: 'Licensed and original franchises featured in pinball.' },
  schemaOrg: { types: ['CreativeWork'] },
};
