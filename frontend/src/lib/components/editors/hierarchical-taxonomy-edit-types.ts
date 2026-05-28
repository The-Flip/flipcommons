import type { RichTextSchema } from '$lib/api/schema';

/**
 * Structural superset of GameplayFeatureDetailSchema and ThemeDetailSchema —
 * the fields the hierarchical-taxonomy section editors consume.
 */
export type HierarchicalTaxonomyEditView = {
  name: string;
  slug: string;
  description: RichTextSchema;
  parents: { name: string; public_id: string }[];
  aliases: string[];
};
