import type { EditSectionDef } from '$lib/components/pages/record/edit/editors/edit-section-def';

export type SystemEditSectionKey = 'name' | 'description' | 'manufacturer' | 'technology';

export type SystemEditSectionDef = EditSectionDef<SystemEditSectionKey>;

export const SYSTEM_EDIT_SECTIONS: SystemEditSectionDef[] = [
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
    key: 'manufacturer',
    segment: 'manufacturer',
    label: 'Manufacturer',
    showCitation: true,
    showMixedEditWarning: false,
    usesSectionEditorForm: true,
  },
  {
    key: 'technology',
    segment: 'technology',
    label: 'Technology',
    showCitation: true,
    showMixedEditWarning: false,
    usesSectionEditorForm: true,
  },
];

export function findSystemSectionBySegment(segment: string): SystemEditSectionDef | undefined {
  return SYSTEM_EDIT_SECTIONS.find((section) => section.segment === segment);
}

export function findSystemSectionByKey(
  key: SystemEditSectionKey,
): SystemEditSectionDef | undefined {
  return SYSTEM_EDIT_SECTIONS.find((section) => section.key === key);
}

export function defaultSystemSectionSegment(): string {
  return 'name';
}
