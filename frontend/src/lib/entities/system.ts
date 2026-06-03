import type { SystemDetailSchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const system: EntityInfo<SystemDetailSchema> = {
  entityType: 'system',
  listing: { description: 'Hardware platforms and operating systems that power pinball machines.' },
  schemaOrg: { types: ['CreativeWork'], relationshipMap: { manufacturer: 'producer' } },
};
