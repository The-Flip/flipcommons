import type { ManufacturerDetailSchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const manufacturer: EntityInfo<ManufacturerDetailSchema> = {
  entityType: 'manufacturer',
  schemaOrg: { types: ['Brand'], fieldMap: { logo_url: 'logo', website: 'url' } },
};
