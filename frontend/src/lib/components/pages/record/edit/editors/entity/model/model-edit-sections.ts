import type { EditSectionDef } from '$lib/components/pages/record/edit/editors/edit-section-def';

export type ModelEditSectionKey =
  | 'name'
  | 'basics'
  | 'overview'
  | 'technology'
  | 'features'
  | 'people'
  | 'related-models'
  | 'external-data'
  | 'media';

export type ModelEditSectionDef = EditSectionDef<ModelEditSectionKey> & {
  /** URL segment for the mobile edit route, e.g. 'external-data' */
  /** false for media — uses immediate-action Modal, not SectionEditorForm */
  usesSectionEditorForm: boolean;
  /**
   * Hide when the model's identity is title-owned (single-model titles). Per
   * ModelAndTitleUX.md, name/slug/abbreviations on single-model titles live on
   * the Title row; the model-side editor must not surface them at all.
   */
  hideOnTitleOwnedIdentity?: boolean;
};

export const MODEL_EDIT_SECTIONS: ModelEditSectionDef[] = [
  {
    key: 'name',
    segment: 'name',
    label: 'Name',
    showCitation: true,
    showMixedEditWarning: false,
    usesSectionEditorForm: true,
    hideOnTitleOwnedIdentity: true,
  },
  {
    key: 'basics',
    segment: 'basics',
    label: 'Basics',
    showCitation: true,
    showMixedEditWarning: true,
    usesSectionEditorForm: true,
  },
  {
    key: 'overview',
    segment: 'overview',
    label: 'Overview',
    showCitation: false,
    showMixedEditWarning: false,
    usesSectionEditorForm: true,
  },
  {
    key: 'technology',
    segment: 'technology',
    label: 'Technology',
    showCitation: true,
    showMixedEditWarning: true,
    usesSectionEditorForm: true,
  },
  {
    key: 'features',
    segment: 'features',
    label: 'Features',
    showCitation: true,
    showMixedEditWarning: true,
    usesSectionEditorForm: true,
  },
  {
    key: 'people',
    segment: 'people',
    label: 'People',
    showCitation: true,
    showMixedEditWarning: true,
    usesSectionEditorForm: true,
  },
  {
    key: 'related-models',
    segment: 'related-models',
    label: 'Related Models',
    showCitation: true,
    showMixedEditWarning: true,
    usesSectionEditorForm: true,
  },
  {
    key: 'media',
    segment: 'media',
    label: 'Media',
    showCitation: false,
    showMixedEditWarning: false,
    usesSectionEditorForm: false,
  },
  {
    key: 'external-data',
    segment: 'external-data',
    label: 'External Data',
    showCitation: true,
    showMixedEditWarning: true,
    usesSectionEditorForm: true,
  },
];

export function findSectionByKey(key: string): ModelEditSectionDef | undefined {
  return MODEL_EDIT_SECTIONS.find((s) => s.key === key);
}

export function findSectionBySegment(segment: string): ModelEditSectionDef | undefined {
  return MODEL_EDIT_SECTIONS.find((s) => s.segment === segment);
}

export function modelSectionsFor(hasTitleOwnedIdentity: boolean): ModelEditSectionDef[] {
  return hasTitleOwnedIdentity
    ? MODEL_EDIT_SECTIONS.filter((s) => !s.hideOnTitleOwnedIdentity)
    : MODEL_EDIT_SECTIONS;
}
