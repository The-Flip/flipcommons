import type { EditSectionDef } from '$lib/components/pages/record/edit/editors/edit-section-def';

export type CorporateEntityEditSectionKey = 'name' | 'description' | 'basics' | 'aliases';

export type CorporateEntityEditSectionDef = EditSectionDef<CorporateEntityEditSectionKey> & {
  usesSectionEditorForm: boolean;
};

export const CORPORATE_ENTITY_EDIT_SECTIONS: CorporateEntityEditSectionDef[] = [
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
    key: 'basics',
    segment: 'basics',
    label: 'Basics',
    showCitation: true,
    showMixedEditWarning: true,
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
];

export function findCorporateEntitySectionBySegment(
  segment: string,
): CorporateEntityEditSectionDef | undefined {
  return CORPORATE_ENTITY_EDIT_SECTIONS.find((section) => section.segment === segment);
}

export function findCorporateEntitySectionByKey(
  key: CorporateEntityEditSectionKey,
): CorporateEntityEditSectionDef | undefined {
  return CORPORATE_ENTITY_EDIT_SECTIONS.find((section) => section.key === key);
}

export function defaultCorporateEntitySectionSegment(): string {
  return 'name';
}
