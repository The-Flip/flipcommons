import type { EditSectionDef } from '$lib/components/pages/record/edit/editors/edit-section-def';

export type HierarchicalTaxonomyEditSectionKey =
  | 'name'
  | 'description'
  | 'aliases'
  | 'parents'
  | 'media';

export type HierarchicalTaxonomyEditSectionDef =
  EditSectionDef<HierarchicalTaxonomyEditSectionKey> & {
    usesSectionEditorForm: boolean;
  };

/**
 * Base sections for hierarchical taxonomies (gameplay-features, themes).
 * The `parents` section's label is a placeholder; each entity's layout
 * remaps it (e.g. "Parent Themes" / "Parent Features") before passing
 * the array to TaxonomyDetailBaseLayout.
 *
 * Gameplay-features (and any future hierarchical taxonomy with media)
 * concatenates MEDIA_SECTION; themes ignores it.
 */
export const HIERARCHICAL_TAXONOMY_EDIT_SECTIONS: HierarchicalTaxonomyEditSectionDef[] = [
  {
    key: 'name',
    segment: 'name',
    label: 'Name',
    showCitation: true,
    showMixedEditWarning: false,
    usesSectionEditorForm: true,
  },
  {
    key: 'description',
    segment: 'description',
    label: 'Description',
    showCitation: false,
    showMixedEditWarning: false,
    usesSectionEditorForm: true,
  },
  {
    key: 'aliases',
    segment: 'aliases',
    label: 'Aliases',
    showCitation: true,
    showMixedEditWarning: false,
    usesSectionEditorForm: true,
  },
  {
    key: 'parents',
    segment: 'parents',
    label: 'Parents',
    showCitation: true,
    showMixedEditWarning: false,
    usesSectionEditorForm: true,
  },
];

export const MEDIA_SECTION: HierarchicalTaxonomyEditSectionDef = {
  key: 'media',
  segment: 'media',
  label: 'Media',
  showCitation: false,
  showMixedEditWarning: false,
  usesSectionEditorForm: false,
};

export function defaultHierarchicalTaxonomySectionSegment(): string {
  return 'name';
}
