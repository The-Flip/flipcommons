import { describe, expect, it } from 'vitest';

import {
  MODEL_EDIT_SECTIONS,
  findSectionByKey,
  findSectionBySegment,
  modelSectionsFor,
} from './model-edit-sections';

describe('model edit sections', () => {
  it('uses the requested section ordering', () => {
    expect(MODEL_EDIT_SECTIONS.map((s) => s.key)).toEqual([
      'name',
      'basics',
      'overview',
      'technology',
      'features',
      'people',
      'related-models',
      'media',
      'external-data',
    ]);
  });

  it('looks up sections by key and segment', () => {
    expect(findSectionByKey('name')?.label).toBe('Name');
    expect(findSectionBySegment('external-data')?.key).toBe('external-data');
    expect(findSectionBySegment('missing')).toBeUndefined();
  });

  it('does not show the mixed-edit warning for the name section', () => {
    expect(findSectionByKey('name')?.showMixedEditWarning).toBe(false);
  });

  it('modelSectionsFor returns every section when identity is model-owned', () => {
    const keys = modelSectionsFor(false).map((s) => s.key);
    expect(keys).toEqual(MODEL_EDIT_SECTIONS.map((s) => s.key));
  });

  it('modelSectionsFor hides the Name section when identity is title-owned', () => {
    const keys = modelSectionsFor(true).map((s) => s.key);
    expect(keys).not.toContain('name');
    // Every other section stays.
    for (const s of MODEL_EDIT_SECTIONS) {
      if (s.key !== 'name') expect(keys).toContain(s.key);
    }
  });
});
