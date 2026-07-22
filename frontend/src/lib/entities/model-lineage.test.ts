import { describe, it, expect } from 'vitest';

import { makeModelDetail } from '$lib/api/detail-fixtures';
import { ENTITY_META } from './entity-meta';
import {
  MODEL_LINEAGE_RELATIONS,
  modelEdgeSections,
  modelExportEditionSection,
  modelLineageSections,
  titleModelsSubject,
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
      remake_of: { name: 'Video Pinball', public_id: 'video-pinball', year: 1978 },
      variant_of: { name: 'Parent', public_id: 'parent', year: 1980 },
    });

    const keys = modelLineageSections(model).map((s) => s.relation.key);

    // variant_of precedes remake_of in MODEL_LINEAGE_RELATIONS.
    expect(keys).toEqual(['variant_of', 'remake_of']);
  });

  it('resolves a reverse list to its full set of links', () => {
    const model = makeModelDetail({
      remakes: [
        { name: 'Rugby', public_id: 'rugby-sidam', year: 1979 },
        { name: 'Clone', public_id: 'clone', year: 1981 },
      ],
    });

    const [section] = modelLineageSections(model);
    expect(section.relation.key).toBe('remakes');
    expect(section.links.map((l) => l.public_id)).toEqual(['rugby-sidam', 'clone']);
  });

  describe('manufacturer disambiguation', () => {
    // A remake often keeps the original's name, so with no maker shown it reads
    // as a relation to itself. The maker is surfaced only when it differs.
    const gottlieb = { name: 'D. Gottlieb & Company', public_id: 'gottlieb' };
    const zaccaria = { name: 'Zaccaria', public_id: 'zaccaria' };

    it('shows the maker when it differs from the subject', () => {
      const model = makeModelDetail({
        manufacturer: gottlieb,
        remakes: [
          { name: 'Jungle Life', public_id: 'jungle-life-zaccaria', manufacturer: zaccaria },
        ],
      });

      const [section] = modelLineageSections(model);
      // Keeps the full ref (name + public_id) so the maker renders as a link.
      expect(section.links[0].manufacturer).toEqual({ kind: 'known', ref: zaccaria });
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
        remakes: [
          { name: 'Jungle Life', public_id: 'jungle-life-zaccaria', manufacturer: zaccaria },
        ],
      });

      const [section] = modelLineageSections(model);
      expect(section.links[0].manufacturer).toEqual({ kind: 'known', ref: zaccaria });
    });

    it('surfaces an unknown maker against a known subject (also disambiguating)', () => {
      const model = makeModelDetail({
        manufacturer: gottlieb,
        remakes: [{ name: 'Jungle Life', public_id: 'jungle-life-emmepi' }],
      });

      const [section] = modelLineageSections(model);
      expect(section.links[0].manufacturer).toEqual({ kind: 'unknown' });
    });

    it('omits the maker when neither the subject nor the link has one', () => {
      const model = makeModelDetail({
        manufacturer: null,
        remakes: [{ name: 'Jungle Life', public_id: 'jungle-life-emmepi' }],
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
      expect(section.links[0].manufacturer).toEqual({ kind: 'known', ref: zaccaria });
    });
  });
});

describe('modelEdgeSections', () => {
  const galaxie = {
    name: 'Galaxie',
    public_id: 'galaxie',
    year: 1971,
    manufacturer: { name: 'D. Gottlieb & Company', public_id: 'gottlieb' },
  };

  it('returns nothing for a model with no edges', () => {
    expect(modelEdgeSections(makeModelDetail())).toEqual([]);
  });

  it('groups outbound edges under their lead phrase, one target line per edge', () => {
    const model = makeModelDetail({
      relationships: [
        {
          relationship_type: 'conversion_kit',
          license_status: 'unknown',
          target_machine: galaxie,
          target_label: '',
        },
        {
          relationship_type: 'conversion_kit',
          license_status: 'unknown',
          target_machine: null,
          target_label: 'several Gottlieb EM models',
        },
        {
          relationship_type: 'copy',
          license_status: 'unlicensed',
          target_machine: galaxie,
          target_label: '',
        },
      ],
    });

    const sections = modelEdgeSections(model);
    expect(sections.map((s) => s.heading)).toEqual(['Conversion kit for', 'Bootleg of']);

    // Every section carries an explanatory preface, like the lineage notes
    // ("This game is a remake of:").
    expect(sections.map((s) => s.note)).toEqual([
      'This game is a kit that converts:',
      'This game is an unauthorized copy of:',
    ]);

    // A machine target resolves like any lineage link (name + maker + year);
    // the label target has no machine to link.
    const [kit, bootleg] = sections;
    expect(kit.targets).toEqual([
      {
        machine: {
          name: 'Galaxie',
          public_id: 'galaxie',
          year: 1971,
          manufacturer: {
            kind: 'known',
            ref: { name: 'D. Gottlieb & Company', public_id: 'gottlieb' },
          },
        },
        label: '',
      },
      { machine: null, label: 'several Gottlieb EM models' },
    ]);
    expect(bootleg.targets[0].machine?.public_id).toBe('galaxie');
  });

  it('suppresses a machine target maker that matches the subject, like lineage links', () => {
    const model = makeModelDetail({
      manufacturer: { name: 'D. Gottlieb & Company', public_id: 'gottlieb' },
      relationships: [
        {
          relationship_type: 'copy',
          license_status: 'unknown',
          target_machine: galaxie,
          target_label: '',
        },
      ],
    });

    const [section] = modelEdgeSections(model);
    expect(section.targets[0].machine?.manufacturer).toBeNull();
  });

  it('suppresses a year that matches the subject, in lineage and edge sections alike', () => {
    const model = makeModelDetail({
      year: 1971,
      remakes: [{ name: 'Galaxie Remake', public_id: 'galaxie-remake', year: 1971 }],
      relationships: [
        {
          relationship_type: 'copy',
          license_status: 'unknown',
          target_machine: galaxie, // 1971 — matches the subject
          target_label: '',
        },
        {
          relationship_type: 'conversion',
          license_status: 'unknown',
          target_machine: { name: 'Other', public_id: 'other', year: 1976 },
          target_label: '',
        },
      ],
    });

    const [lineage] = modelLineageSections(model);
    expect(lineage.links[0].year).toBeNull();

    const [copy, conversion] = modelEdgeSections(model);
    expect(copy.targets[0].machine?.year).toBeNull();
    expect(conversion.targets[0].machine?.year).toBe(1976);
  });

  it('splits same-kind edges with different licenses into separate sections', () => {
    const model = makeModelDetail({
      relationships: [
        {
          relationship_type: 'copy',
          license_status: 'licensed',
          target_machine: galaxie,
          target_label: '',
        },
        {
          relationship_type: 'copy',
          license_status: 'unknown',
          target_machine: { name: 'Other', public_id: 'other' },
          target_label: '',
        },
      ],
    });

    expect(modelEdgeSections(model).map((s) => s.heading)).toEqual(['Licensed copy of', 'Copy of']);
  });

  it('renders inbound edges under plural headings after the outbound sections', () => {
    const model = makeModelDetail({
      relationships: [
        {
          relationship_type: 'conversion',
          license_status: 'unknown',
          target_machine: galaxie,
          target_label: '',
        },
      ],
      inbound_relationships: [
        {
          relationship_type: 'copy',
          license_status: 'unlicensed',
          source_machine: { name: 'Rugby', public_id: 'rugby-sidam', year: 1979 },
        },
        {
          relationship_type: 'conversion_kit',
          license_status: 'licensed',
          source_machine: { name: 'Wizard Kit', public_id: 'wizard-kit' },
        },
      ],
    });

    const sections = modelEdgeSections(model);
    expect(sections.map((s) => s.heading)).toEqual([
      'Conversion of',
      'Bootlegs',
      'Licensed Conversion Kits',
    ]);
    expect(sections.map((s) => s.note)).toEqual([
      'This game was rebuilt from the hardware of:',
      'Unauthorized copies of this game:',
      'Officially licensed kits that convert this machine into a different game:',
    ]);
    expect(sections[1].targets).toEqual([
      {
        machine: { name: 'Rugby', public_id: 'rugby-sidam', year: 1979, manufacturer: null },
        label: '',
      },
    ]);
  });
});

describe('titleModelsSubject', () => {
  const gottlieb = { name: 'D. Gottlieb & Company', public_id: 'gottlieb' };
  const zaccaria = { name: 'Zaccaria', public_id: 'zaccaria' };

  it('treats a maker and year every model shares as the subject', () => {
    const subject = titleModelsSubject([
      { name: 'A', public_id: 'a', year: 1979, manufacturer: gottlieb },
      { name: 'B', public_id: 'b', year: 1979, manufacturer: gottlieb },
    ]);

    expect(subject).toEqual({ manufacturer: 'D. Gottlieb & Company', year: 1979 });
  });

  it('yields no subject for a mixed list, so makers and years stay visible', () => {
    const subject = titleModelsSubject([
      { name: 'A', public_id: 'a', year: 1979, manufacturer: gottlieb },
      { name: 'B', public_id: 'b', year: 1981, manufacturer: zaccaria },
    ]);

    expect(subject).toEqual({ manufacturer: null, year: null });
  });

  it('yields no subject for an empty list', () => {
    expect(titleModelsSubject([])).toEqual({ manufacturer: null, year: null });
  });

  it('lets an explicit maker and year override the unanimous fallback', () => {
    const subject = titleModelsSubject(
      [{ name: 'A', public_id: 'a', year: 1979, manufacturer: gottlieb }],
      { manufacturer: 'Zaccaria', year: 1981 },
    );

    expect(subject).toEqual({ manufacturer: 'Zaccaria', year: 1981 });
  });

  it('keeps an explicit null subject rather than falling back to the unanimous value', () => {
    const subject = titleModelsSubject(
      [{ name: 'A', public_id: 'a', year: 1979, manufacturer: gottlieb }],
      { manufacturer: null, year: null },
    );

    expect(subject).toEqual({ manufacturer: null, year: null });
  });
});

describe('modelExportEditionSection', () => {
  const italy = { name: 'Italy', public_id: 'italy' };
  const original = { name: 'Big Ben', public_id: 'big-ben', year: 1975 };

  it('returns nothing for a model with no export facts', () => {
    expect(modelExportEditionSection(makeModelDetail())).toBeNull();
  });

  it('carries the original and its named markets', () => {
    const section = modelExportEditionSection(
      makeModelDetail({
        export_edition_of: original,
        export_markets: [
          { target_location: italy, target_label: '' },
          { target_location: null, target_label: 'Europe' },
        ],
      }),
    );

    expect(section?.original?.public_id).toBe('big-ben');
    expect(section?.markets).toEqual([
      { location: italy, label: '' },
      { location: null, label: 'Europe' },
    ]);
  });

  // The unknown-market row asserts "built for export" and nothing more — the
  // sentence must not invent a market for it.
  it('drops the unknown-market row, keeping the section', () => {
    const section = modelExportEditionSection(
      makeModelDetail({ export_markets: [{ target_location: null, target_label: '' }] }),
    );

    expect(section).not.toBeNull();
    expect(section?.markets).toEqual([]);
    expect(section?.original).toBeNull();
  });

  it('is rendered on its own, not as a generic lineage section', () => {
    const model = makeModelDetail({ export_edition_of: original });

    expect(modelLineageSections(model)).toEqual([]);
    expect(modelExportEditionSection(model)?.original?.name).toBe('Big Ben');
  });
});
