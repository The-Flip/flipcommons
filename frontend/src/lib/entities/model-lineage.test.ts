import { describe, it, expect } from 'vitest';

import { makeModelDetail } from '$lib/api/detail-fixtures';
import { ENTITY_META } from './entity-meta';
import {
  MODEL_LINEAGE_RELATIONS,
  modelLineageRelation,
  modelLineageSections,
} from './model-lineage';

// Guards that the forward-FK descriptors stay in sync with the backend's
// model↔model self-relations. entity-meta.ts is generated from the Django
// models, so when a new self-FK is added there `make codegen` updates
// ENTITY_META and this test fails until a descriptor is declared — which is
// what makes "add a relation once" hold: the shared surfaces render from
// MODEL_LINEAGE_RELATIONS, and this stops a new FK from silently going unshown.
describe('model lineage vs entity-meta', () => {
  it('declares exactly the forward model↔model FKs that ENTITY_META knows', () => {
    const forwardSelfFks = Object.entries(ENTITY_META.model.relationships)
      .filter(([, r]) => r.entity_target_type === 'model' && !r.many)
      .map(([key]) => key)
      .sort();

    const declaredForward = MODEL_LINEAGE_RELATIONS.filter((r) => !r.many)
      .map((r) => r.key)
      .sort();

    expect(declaredForward).toEqual(forwardSelfFks);
  });
});

describe('modelLineageSections', () => {
  it('returns nothing for a model with no lineage links', () => {
    expect(modelLineageSections(makeModelDetail())).toEqual([]);
  });

  it('includes only non-empty relations, in declaration order', () => {
    const model = makeModelDetail({
      bootleg_of: { name: 'Video Pinball', public_id: 'video-pinball', year: 1978 },
      variant_of: { name: 'Parent', public_id: 'parent', year: 1980 },
    });

    const keys = modelLineageSections(model).map((s) => s.relation.key);

    // variant_of precedes bootleg_of in MODEL_LINEAGE_RELATIONS.
    expect(keys).toEqual(['variant_of', 'bootleg_of']);
  });

  it('resolves a reverse list to its full set of links', () => {
    const model = makeModelDetail({
      bootlegs: [
        { name: 'Rugby', public_id: 'rugby-sidam', year: 1979 },
        { name: 'Clone', public_id: 'clone', year: 1981 },
      ],
    });

    const [section] = modelLineageSections(model);
    expect(section.relation.key).toBe('bootlegs');
    expect(section.links.map((l) => l.public_id)).toEqual(['rugby-sidam', 'clone']);
  });

  describe('manufacturer disambiguation', () => {
    // A bootleg keeps the original's name, so with no maker shown it reads as a
    // relation to itself. The maker is surfaced only when it differs.
    const gottlieb = { name: 'D. Gottlieb & Company', public_id: 'gottlieb' };
    const zaccaria = { name: 'Zaccaria', public_id: 'zaccaria' };

    it('shows the maker when it differs from the subject', () => {
      const model = makeModelDetail({
        manufacturer: gottlieb,
        bootlegs: [
          { name: 'Jungle Life', public_id: 'jungle-life-zaccaria', manufacturer: zaccaria },
        ],
      });

      const [section] = modelLineageSections(model);
      // Keeps the full ref (name + public_id) so the maker renders as a link.
      expect(section.links[0].manufacturer).toEqual(zaccaria);
    });

    it('omits the maker when it matches the subject', () => {
      const model = makeModelDetail({
        manufacturer: gottlieb,
        remakes: [{ name: 'Jungle Life 2', public_id: 'jungle-life-2', manufacturer: gottlieb }],
      });

      const [section] = modelLineageSections(model);
      expect(section.links[0].manufacturer).toBeNull();
    });

    it('shows the maker when the subject has none (still disambiguating)', () => {
      const model = makeModelDetail({
        manufacturer: null,
        bootlegs: [
          { name: 'Jungle Life', public_id: 'jungle-life-zaccaria', manufacturer: zaccaria },
        ],
      });

      const [section] = modelLineageSections(model);
      expect(section.links[0].manufacturer?.name).toBe('Zaccaria');
    });

    it('omits the maker when the link has none', () => {
      const model = makeModelDetail({
        manufacturer: gottlieb,
        bootlegs: [{ name: 'Jungle Life', public_id: 'jungle-life-emmepi' }],
      });

      const [section] = modelLineageSections(model);
      expect(section.links[0].manufacturer).toBeNull();
    });

    it('disambiguates variant links too, not only ModelRef relations', () => {
      const model = makeModelDetail({
        manufacturer: gottlieb,
        variants: [
          {
            name: 'Jungle Life',
            public_id: 'jungle-life-alt',
            variant_features: [],
            manufacturer: zaccaria,
          },
        ],
      });

      const [section] = modelLineageSections(model);
      expect(section.relation.key).toBe('variants');
      expect(section.links[0].manufacturer?.name).toBe('Zaccaria');
    });
  });
});

describe('modelLineageRelation', () => {
  it('looks up a relation by key', () => {
    expect(modelLineageRelation('bootlegs').heading).toBe('Bootlegs');
  });

  it('throws on an unknown key', () => {
    // @ts-expect-error — exercising the runtime guard with an invalid key.
    expect(() => modelLineageRelation('nope')).toThrow();
  });
});
