import type { FranchiseDetailSchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const franchise: EntityInfo<FranchiseDetailSchema> = {
  entityType: 'franchise',
  schemaOrg: { types: ['CreativeWork'] },
};
