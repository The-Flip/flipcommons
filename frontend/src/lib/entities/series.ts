import type { SeriesDetailSchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const series: EntityInfo<SeriesDetailSchema> = {
  entityType: 'series',
  schemaOrg: { types: ['CreativeWorkSeries'] },
};
