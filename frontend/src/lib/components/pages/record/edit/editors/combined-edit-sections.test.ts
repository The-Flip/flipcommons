/**
 * Registry smoke test for the combined section list.
 *
 * The Title layout renders a section-editor for each key in combinedSectionsFor,
 * keyed by composite `${tier}:${key}`. If someone adds a section to either
 * MODEL_EDIT_SECTIONS or TITLE_EDIT_SECTIONS without also wiring the layout's
 * `editor` snippet, nothing fails at build time — but users get a silent
 * no-op when they pick the new menu item. This test guards that by freezing
 * the expected key set.
 *
 * Update flow: when adding/removing/renaming a section, update BOTH the
 * registry and the expected set below, AND wire the layout's editor snippet
 * branch for the new composite key.
 */

import { describe, expect, it } from 'vitest';
import { combinedSectionsFor } from './combined-edit-sections';

describe('combinedSectionsFor', () => {
  it('multi-model returns the title-tier sections in natural order with plain labels', () => {
    const out = combinedSectionsFor(false);
    expect(out.map((s) => s.key)).toEqual([
      'title:name',
      'title:overview',
      'title:franchise',
      'title:external-data',
    ]);
    expect(out.map((s) => s.menuLabel)).toEqual(['Name', 'Overview', 'Franchise', 'External Data']);
    expect(out.every((s) => s.tier === 'title')).toBe(true);
  });

  it('single-model interleaves title and model sections in the spec ordering', () => {
    const out = combinedSectionsFor(true);
    expect(out.map((s) => s.key)).toEqual([
      'title:name',
      'model:basics',
      'model:overview',
      'title:franchise',
      'model:technology',
      'model:features',
      'model:people',
      'model:related-models',
      'model:media',
      'model:external-data',
      'title:external-data',
    ]);
  });

  it('single-model labels only disambiguate where title + model collide', () => {
    const byKey = new Map(combinedSectionsFor(true).map((s) => [s.key, s.menuLabel]));
    // Title-tier Name has no model counterpart, so label stays plain.
    expect(byKey.get('title:name')).toBe('Name');
    expect(byKey.get('title:franchise')).toBe('Franchise');
    // external-data exists on both tiers, so title's is disambiguated.
    expect(byKey.get('title:external-data')).toBe('External Data - Title');
    expect(byKey.get('model:external-data')).toBe('External Data');
    expect(byKey.get('model:basics')).toBe('Basics');
  });

  it('every composite key is uniquely namespaced by tier', () => {
    for (const isSingleModel of [true, false]) {
      const out = combinedSectionsFor(isSingleModel);
      const keys = out.map((s) => s.key);
      expect(new Set(keys).size).toBe(keys.length);
    }
  });

  it('single-model omits title:overview (description is model-owned)', () => {
    const keys = combinedSectionsFor(true).map((s) => s.key);
    expect(keys).not.toContain('title:overview');
  });
});
