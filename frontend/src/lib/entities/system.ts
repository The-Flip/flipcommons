import type { SystemDetailSchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const system: EntityInfo<SystemDetailSchema> = {
  entityType: 'system',
  schemaOrg: { types: ['CreativeWork'], relationshipMap: { manufacturer: 'producer' } },
};
