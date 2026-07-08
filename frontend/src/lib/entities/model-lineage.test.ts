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
