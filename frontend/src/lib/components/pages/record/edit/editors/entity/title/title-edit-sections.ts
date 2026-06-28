import type { EditSectionDef } from '$lib/components/pages/record/edit/editors/edit-section-def';

export type TitleEditSectionKey = 'name' | 'overview' | 'franchise' | 'external-data';

export type TitleEditSectionDef = EditSectionDef<TitleEditSectionKey> & {
  /** URL segment for the edit route */
  /** False when the section is hidden for single-model titles (e.g. Overview — description is Model-owned). */
  includeInSingleModel: boolean;
};

const TITLE_EDIT_SECTIONS: TitleEditSectionDef[] = [
  {
    key: 'name',
    segment: 'name',
    label: 'Name',
    showCitation: true,
    showMixedEditWarning: false,
    includeInSingleModel: true,
  },
  {
    key: 'overview',
    segment: 'overview',
    label: 'Overview',
    showCitation: false,
    showMixedEditWarning: false,
    includeInSingleModel: false,
  },
  {
    key: 'franchise',
    segment: 'franchise',
    label: 'Franchise',
    showCitation: true,
    showMixedEditWarning: true,
    includeInSingleModel: true,
  },
  {
    key: 'external-data',
    segment: 'external-data',
    label: 'External Data',
    showCitation: true,
    showMixedEditWarning: true,
    includeInSingleModel: true,
  },
];

export function findTitleSectionBySegment(segment: string): TitleEditSectionDef | undefined {
  return TITLE_EDIT_SECTIONS.find((s) => s.segment === segment);
}

export function titleSectionsFor(isSingleModel: boolean): TitleEditSectionDef[] {
  return isSingleModel
    ? TITLE_EDIT_SECTIONS.filter((s) => s.includeInSingleModel)
    : TITLE_EDIT_SECTIONS;
}

export function defaultTitleSectionSegment(isSingleModel: boolean): string {
  return isSingleModel ? 'franchise' : 'overview';
}
