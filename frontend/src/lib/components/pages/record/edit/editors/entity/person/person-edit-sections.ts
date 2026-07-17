import type { EditSectionDef } from '$lib/components/pages/record/edit/editors/edit-section-def';

export type PersonEditSectionKey = 'name' | 'bio' | 'details' | 'media';

export type PersonEditSectionDef = EditSectionDef<PersonEditSectionKey>;

export const PERSON_EDIT_SECTIONS: PersonEditSectionDef[] = [
  {
    key: 'name',
    segment: 'name',
    label: 'Name',
    showCitation: true,
    showMixedEditWarning: false,
    usesSectionEditorForm: true,
  },
  {
    key: 'bio',
    segment: 'bio',
    label: 'Bio',
    showCitation: false,
    showMixedEditWarning: false,
    usesSectionEditorForm: true,
  },
  {
    key: 'details',
    segment: 'details',
    label: 'Details',
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
];

export function findPersonSectionBySegment(segment: string): PersonEditSectionDef | undefined {
  return PERSON_EDIT_SECTIONS.find((section) => section.segment === segment);
}

export function findPersonSectionByKey(
  key: PersonEditSectionKey,
): PersonEditSectionDef | undefined {
  return PERSON_EDIT_SECTIONS.find((section) => section.key === key);
}

export function defaultPersonSectionSegment(): string {
  return 'name';
}
