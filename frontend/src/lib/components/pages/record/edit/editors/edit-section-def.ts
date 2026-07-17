export type EditSectionDef<TKey extends string> = {
  key: TKey;
  segment: string;
  label: string;
  showCitation: boolean;
  showMixedEditWarning: boolean;
  /**
   * True when the section edits through `SectionEditorForm` (the Save/Cancel
   * form host); false for immediate-action sections (e.g. media) that render
   * their own body with a Done button instead.
   */
  usesSectionEditorForm: boolean;
};
