export type EditSectionDef<TKey extends string> = {
  key: TKey;
  segment: string;
  label: string;
  showCitation: boolean;
  showMixedEditWarning: boolean;
};
