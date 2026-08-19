/**
 * Combined section registry for the Title reader's edit menu.
 *
 * Single-model titles need to edit both Title- and Model-tier sections from one
 * menu and one modal host. Section-key collisions (`name`, `external-data`)
 * are resolved with composite keys of the form `${tier}:${key}`, so a single
 * SectionEditorHost (generic over TSectionKey extends string) handles both
 * tiers without host-side changes.
 *
 * The canonical per-tier registries (MODEL_EDIT_SECTIONS, TITLE_EDIT_SECTIONS)
 * stay untouched — they're still consumed by the dedicated edit routes.
 */

import {
  MODEL_EDIT_SECTIONS,
  type ModelEditSectionDef,
} from '$lib/components/pages/record/edit/editors/entity/model/model-edit-sections';
import {
  titleSectionsFor,
  type TitleEditSectionDef,
} from '$lib/components/pages/record/edit/editors/entity/title/title-edit-sections';

type SectionTier = 'title' | 'model';
export type CombinedSectionKey = `${SectionTier}:${string}`;

export type CombinedSectionDef = {
  key: CombinedSectionKey;
  tier: SectionTier;
  segment: string;
  /** Plain label, used as modal heading (e.g. "Name"). */
  label: string;
  /** Label shown in the combined dropdown (disambiguated where title + model collide). */
  menuLabel: string;
  showCitation: boolean;
  showMixedEditWarning: boolean;
  usesSectionEditorForm: boolean;
};

function toTitleDef(s: TitleEditSectionDef, menuLabel: string): CombinedSectionDef {
  return {
    key: `title:${s.key}`,
    tier: 'title',
    segment: s.segment,
    label: s.label,
    menuLabel,
    showCitation: s.showCitation,
    showMixedEditWarning: s.showMixedEditWarning,
    // All title-tier editors use SectionEditorForm — no immediate-action title editors exist.
    usesSectionEditorForm: true,
  };
}

function toModelDef(s: ModelEditSectionDef): CombinedSectionDef {
  return {
    key: `model:${s.key}`,
    tier: 'model',
    segment: s.segment,
    label: s.label,
    menuLabel: s.label,
    showCitation: s.showCitation,
    showMixedEditWarning: s.showMixedEditWarning,
    usesSectionEditorForm: s.usesSectionEditorForm,
  };
}

/**
 * Single-model ordering (edits both tiers from one menu):
 *   1. title:name        — identity edits land on the Title row
 *   2. model:basics      — manufacturer / production + project dates
 *   3. model:overview
 *   4. title:franchise
 *   5. model:technology, features, people, related-models, media
 *   6. model:external-data, title:external-data (disambiguated)
 *
 * The Title-tier `name` section uses the plain label "Name" because the model
 * has no Name section to collide with. The `external-data` sections collide,
 * so the title one is relabeled for the menu.
 *
 * Multi-model returns the natural title order.
 */
export function combinedSectionsFor(isSingleModel: boolean): CombinedSectionDef[] {
  const titleDefs = titleSectionsFor(isSingleModel);

  if (!isSingleModel) {
    return titleDefs.map((s) => toTitleDef(s, s.label));
  }

  const titleByKey = new Map(titleDefs.map((s) => [s.key, s]));
  const modelByKey = new Map(MODEL_EDIT_SECTIONS.map((s) => [s.key, s]));

  const requireTitle = (key: TitleEditSectionDef['key']): TitleEditSectionDef => {
    const s = titleByKey.get(key);
    if (!s) throw new Error(`TITLE_EDIT_SECTIONS missing required "${key}" entry`);
    return s;
  };
  const requireModel = (key: ModelEditSectionDef['key']): ModelEditSectionDef => {
    const s = modelByKey.get(key);
    if (!s) throw new Error(`MODEL_EDIT_SECTIONS missing required "${key}" entry`);
    return s;
  };

  return [
    toTitleDef(requireTitle('name'), 'Name'),
    toModelDef(requireModel('basics')),
    toModelDef(requireModel('overview')),
    toTitleDef(requireTitle('franchise'), 'Franchise'),
    toModelDef(requireModel('technology')),
    toModelDef(requireModel('features')),
    toModelDef(requireModel('people')),
    toModelDef(requireModel('related-models')),
    toModelDef(requireModel('media')),
    toModelDef(requireModel('external-data')),
    toTitleDef(requireTitle('external-data'), 'External Data - Title'),
  ];
}
