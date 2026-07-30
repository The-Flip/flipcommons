import type { TitleDetailSchema } from '$lib/api/schema';
import type { EntityInfo } from './types';

export const title: EntityInfo<TitleDetailSchema> = {
  entityType: 'title',
  listing: {
    // The label everywhere (tab/SEO, visible heading, breadcrumb) matches the
    // listing's row noun — a game is a Title or a Model; the site name
    // supplies the pinball context.
    title: 'Games',
    description:
      'Browse every pinball title in the Flipcommons catalog — the games, their themes, manufacturers and the machines that brought them to life.',
    // A listing row is a Title or a Model under the roll-up, so reader-facing
    // strings call it a game — the either/both case the word is reserved for.
    itemLabel: 'game',
    itemLabelPlural: 'games',
  },
  schemaOrg: {
    types: ['Game'],
    fieldMap: { hero_image_url: 'image' },
    // Distinct properties so the two refs don't collide on one key
    // (relationshipMap assignment overwrites). No `datePublished`: release
    // year lives on the nested Model schema and is emitted on the Model node.
    relationshipMap: { series: 'isPartOf', franchise: 'isBasedOn' },
  },
  externalRefs: {
    fandom_page_id: {
      label: 'Pinball Wiki',
      urlTemplate: 'https://pinball.fandom.com/?curid={id}',
    },
    opdb_id: { identifier: 'OPDB' }, // a Title's opdb_id is a group id; URL is a non-resolvable autoincrement
  },
};
