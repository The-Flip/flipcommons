import type { EditSectionDef } from '$lib/components/pages/record/edit/editors/edit-section-def';

export type LocationEditSectionKey = 'description' | 'basics' | 'divisions' | 'aliases';

export type LocationEditSectionDef = EditSectionDef<LocationEditSectionKey> & {
  usesSectionEditorForm: boolean;
  /** When true, hide this section unless the row is a country. */
  countryOnly?: boolean;
};

// `name` is intentionally absent: slug is immutable on Location and the
// shared `NameEditor` edits name + slug together. Name editing returns
// once `NameEditor` learns a name-only mode (driven by
// `immutable_after_create`). `parent`, `slug`, and `location_type` are
// frozen by design and not surfaced in the edit menu.
const LOCATION_EDIT_SECTIONS: LocationEditSectionDef[] = [
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
    key: 'divisions',
    segment: 'divisions',
    label: 'Divisions',
    showCitation: true,
    showMixedEditWarning: false,
    usesSectionEditorForm: true,
    countryOnly: true,
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

export function locationEditSectionsFor(
  locationType: string | null | undefined,
): LocationEditSectionDef[] {
  return LOCATION_EDIT_SECTIONS.filter((s) => !s.countryOnly || locationType === 'country');
}

export function findLocationSectionBySegment(segment: string): LocationEditSectionDef | undefined {
  return LOCATION_EDIT_SECTIONS.find((s) => s.segment === segment);
}

export function findLocationSectionByKey(
  key: LocationEditSectionKey,
): LocationEditSectionDef | undefined {
  return LOCATION_EDIT_SECTIONS.find((s) => s.key === key);
}

export function defaultLocationSectionSegment(): string {
  return 'description';
}
