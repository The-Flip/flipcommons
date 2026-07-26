/**
 * Single source of truth for the model↔model lineage relations and their
 * display copy. Every reader surface that shows lineage — the mobile model
 * relationships list, the desktop model sidebar and the single-model title
 * page — renders from this declaration, so a new relation is added once here
 * instead of in near-clone `{#if}` blocks per surface.
 *
 * `entity-meta.ts` only knows the forward FKs (`variant_of`, `remake_of`) and
 * carries no display copy, so the reverse lists and the headings/notes are
 * declared here. `model-lineage.test.ts` guards that the forward set stays in
 * sync with `ENTITY_META`, so a new backend model↔model FK forces a descriptor
 * here rather than silently going unshown. Copy/conversion/kit facts render
 * from `ModelRelationship` edges instead — see {@link modelEdgeSections}.
 */
import type { EntityRef, ModelDetailSchema, ModelRef } from '$lib/api/schema';
import {
  inboundRelationshipHeading,
  inboundRelationshipNote,
  relationshipLead,
  relationshipNote,
} from './relationship-phrase';

/** A related model. Forward-FK and reverse-list targets share this shape. */
export type ModelLineageLink = Pick<ModelRef, 'name' | 'public_id' | 'year' | 'manufacturer'>;

/** Keys on {@link ModelDetailSchema} whose values are model↔model lineage links. */
export type ModelLineageKey =
  | 'variant_of'
  | 'variants'
  | 'variant_siblings'
  | 'remake_of'
  | 'remakes'
  | 'export_edition_of'
  | 'export_editions';

/** Display + accessor descriptor for one lineage relation. */
export interface ModelLineageRelation {
  /** The `ModelDetailSchema` field this relation reads; also the stable `{#each}` key. */
  key: ModelLineageKey;
  /** Section heading. */
  heading: string;
  /** Descriptive copy shown above the links on surfaces that render notes (sidebar, title accordion). */
  note?: string;
  /** `false` for a forward FK (points at one model), `true` for a reverse list. */
  many: boolean;
  /**
   * `true` when a dedicated section renders this relation instead of the
   * generic heading + link-list treatment, so {@link modelLineageSections}
   * skips it. Declared here rather than omitted from the list so the
   * entity-meta sync guard still forces a decision for every forward FK.
   */
  dedicated?: boolean;
  /** Resolves the relation's link targets from a model; `[]` when the relation is absent. */
  resolve: (model: ModelDetailSchema) => ModelLineageLink[];
}

const one = (link: ModelLineageLink | null | undefined): ModelLineageLink[] => (link ? [link] : []);

/**
 * The model↔model lineage relations, in the order every surface renders them:
 * parent → children → siblings, then each lineage kind's forward FK followed by
 * its reverse list.
 */
export const MODEL_LINEAGE_RELATIONS: readonly ModelLineageRelation[] = [
  {
    key: 'variant_of',
    heading: 'Variant Of',
    note: 'This game is a variant of:',
    many: false,
    resolve: (m) => one(m.variant_of),
  },
  {
    key: 'variants',
    heading: 'Variants',
    note: 'These play identically, differing only cosmetically:',
    many: true,
    resolve: (m) => m.variants ?? [],
  },
  {
    key: 'variant_siblings',
    heading: 'Other Variants',
    note: 'Other variants of the same parent:',
    many: true,
    resolve: (m) => m.variant_siblings ?? [],
  },
  {
    key: 'remake_of',
    heading: 'Remake Of',
    note: 'This game is a remake of:',
    many: false,
    resolve: (m) => one(m.remake_of),
  },
  {
    key: 'remakes',
    heading: 'Remakes',
    note: 'Later remakes of this machine:',
    many: true,
    resolve: (m) => m.remakes ?? [],
  },
  {
    key: 'export_edition_of',
    heading: 'Export Edition',
    many: false,
    // Rendered as a sentence alongside the export markets — see
    // {@link modelExportEditionSection}.
    dedicated: true,
    resolve: (m) => one(m.export_edition_of),
  },
  {
    key: 'export_editions',
    heading: 'Export Editions',
    note: 'Editions of this game built for export markets:',
    many: true,
    resolve: (m) => m.export_editions ?? [],
  },
];

/**
 * The manufacturer to show on a related-model line for disambiguation: a `known`
 * manufacturer (rendered as a link to its page) or an `unknown` one (rendered
 * as the "Unknown Manufacturer" label). Unknown is a first-class distinguishing
 * value, not an omission — a related game with an unknown manufacturer is provably not
 * the subject's when the subject's manufacturer *is* known.
 */
export type ManufacturerDisplay = { kind: 'known'; ref: EntityRef } | { kind: 'unknown' };

/**
 * A resolved lineage link ready to render: identity plus the manufacturer to show for
 * disambiguation (or `null` to omit it). Lineage links and edge machine
 * targets both resolve to this shape, so `RelatedModelLink` is the one
 * renderer for a related model across every section.
 */
export interface ModelLineageLinkView {
  name: string;
  public_id: string;
  /** Year to show, or `null` when it matches the subject's year or is unknown. */
  year: number | null;
  /**
   * Manufacturer to show, or `null` when it matches the subject's (including both
   * unknown) so it wouldn't disambiguate. Same-named links (a game and the
   * copies that took its name) otherwise read as a relation to itself, since no
   * reader surface shows a manufacturer; a *differing* manufacturer — a different one,
   * or a missing one against a known subject — is what tells them apart.
   */
  manufacturer: ManufacturerDisplay | null;
}

/** Input for {@link toModelLinkView}: manufacturer and year may be absent entirely (e.g. variant rows). */
export type RelatedModelInput = Pick<ModelRef, 'name' | 'public_id'> &
  Partial<Pick<ModelRef, 'year' | 'manufacturer'>>;

/** The page's subject model, whose manufacturer and year suppress matching values on related-model lines. */
export interface RelatedModelSubject {
  manufacturer: string | null;
  year: number | null;
}

/**
 * Resolve a related model for display: keep the manufacturer and year only when they
 * differ from the subject's (i.e. when they disambiguate). A manufacturer differs when
 * its name isn't the subject's — so a *missing* manufacturer against a known subject
 * surfaces as `unknown`, while both-missing stays omitted. Every surface that
 * renders a `RelatedModelLink` builds its link through this rule.
 */
export function toModelLinkView(
  link: RelatedModelInput,
  subject: RelatedModelSubject,
): ModelLineageLinkView {
  const linkManufacturer = link.manufacturer ?? null;
  const manufacturerDiffers = (linkManufacturer?.name ?? null) !== subject.manufacturer;
  return {
    name: link.name,
    public_id: link.public_id,
    year: link.year != null && link.year !== subject.year ? link.year : null,
    manufacturer: manufacturerDiffers
      ? linkManufacturer
        ? { kind: 'known', ref: linkManufacturer }
        : { kind: 'unknown' }
      : null,
  };
}

/** A lineage relation paired with its resolved, non-empty link list. */
export interface ModelLineageSection {
  relation: ModelLineageRelation;
  links: ModelLineageLinkView[];
}

/**
 * The lineage relations present on `model`, in declaration order, skipping any
 * whose link list is empty. Drives the mobile list and the desktop sidebar, and
 * the "has any lineage" check that gates the mobile Related Models accordion.
 */
export function modelLineageSections(model: ModelDetailSchema): ModelLineageSection[] {
  const subject = modelSubject(model);
  const sections: ModelLineageSection[] = [];
  for (const relation of MODEL_LINEAGE_RELATIONS) {
    if (relation.dedicated) continue;
    const links = relation.resolve(model);
    if (links.length === 0) continue;
    sections.push({
      relation,
      links: links.map((link) => toModelLinkView(link, subject)),
    });
  }
  return sections;
}

/** The suppression subject for a model detail page: the page's own model. */
function modelSubject(model: ModelDetailSchema): RelatedModelSubject {
  return { manufacturer: model.manufacturer?.name ?? null, year: model.year ?? null };
}

/** The value shared by every entry, or `null` when they differ or the list is empty. */
function unanimous<T>(values: readonly (T | null)[]): T | null {
  const first = values[0] ?? null;
  return values.every((v) => (v ?? null) === first) ? first : null;
}

/**
 * The suppression subject for a list of a title's models. An explicit manufacturer or
 * year — the model page passes its own — wins; otherwise a value shared by every
 * model in the list is treated as the title's own, so a uniform list suppresses
 * it and only a mixed list surfaces manufacturers/years. An `undefined` field defers to
 * the unanimous value; an explicit `null` asserts "no subject" and is kept.
 */
export function titleModelsSubject(
  models: readonly RelatedModelInput[],
  explicit: { manufacturer?: string | null; year?: number | null } = {},
): RelatedModelSubject {
  return {
    manufacturer:
      explicit.manufacturer !== undefined
        ? explicit.manufacturer
        : unanimous(models.map((m) => m.manufacturer?.name ?? null)),
    year:
      explicit.year !== undefined ? explicit.year : unanimous(models.map((m) => m.year ?? null)),
  };
}

/**
 * One rendered line of a relationship-edge section: a machine target XOR a
 * plain-text label target, mirroring the edge's own target XOR. Inbound
 * sections put the *source* model here.
 */
export interface ModelEdgeTargetView {
  /** Linked machine (rendered by `RelatedModelLink`, like every lineage link), or `null` for a label target. */
  machine: ModelLineageLinkView | null;
  /** Free-text descriptor when the donor isn't seeded; rendered unlinked — no hyperlink anywhere in it. */
  label: string;
}

/** One heading + lines group of relationship edges sharing a (kind, license). */
export interface ModelEdgeSection {
  /** Stable render key: direction + edge type + license. */
  key: string;
  /** "Bootleg of" (outbound lead phrase) or "Bootlegs" (inbound plural noun). */
  heading: string;
  /** Explanatory preface shown above the targets on surfaces that render notes (sidebar), like {@link ModelLineageRelation.note}. */
  note: string;
  /** One entry per edge — never joined with a connective (AND vs OR is deliberately unmodeled). */
  targets: ModelEdgeTargetView[];
}

/**
 * The model's relationship edges (copy / conversion / conversion kit) grouped
 * into display sections: outbound edges under their lead phrase
 * ("Conversion kit for" → one target line per edge), then inbound edges under
 * the plural heading ("Conversion Kits" → one source line per edge). Groups
 * follow the edges' payload order of first appearance. Rendered by the same
 * surfaces as {@link modelLineageSections}, after the lineage sections, with
 * the same manufacturer/year-disambiguation rule on machine targets.
 */
export function modelEdgeSections(model: ModelDetailSchema): ModelEdgeSection[] {
  const subject = modelSubject(model);
  const machineTarget = (ref: ModelRef): ModelEdgeTargetView => ({
    machine: toModelLinkView(ref, subject),
    label: '',
  });

  const sections = new Map<string, ModelEdgeSection>();
  const section = (key: string, heading: string, note: string): ModelEdgeSection => {
    let existing = sections.get(key);
    if (!existing) {
      existing = { key, heading, note, targets: [] };
      sections.set(key, existing);
    }
    return existing;
  };

  for (const edge of model.relationships ?? []) {
    const key = `outbound:${edge.relationship_type}:${edge.license_status}`;
    const lead = relationshipLead(edge.relationship_type, edge.license_status);
    const note = relationshipNote(edge.relationship_type, edge.license_status);
    section(key, lead, note).targets.push(
      edge.target_machine
        ? machineTarget(edge.target_machine)
        : { machine: null, label: edge.target_label ?? '' },
    );
  }

  for (const edge of model.inbound_relationships ?? []) {
    const key = `inbound:${edge.relationship_type}:${edge.license_status}`;
    const heading = inboundRelationshipHeading(edge.relationship_type, edge.license_status);
    const note = inboundRelationshipNote(edge.relationship_type, edge.license_status);
    section(key, heading, note).targets.push(machineTarget(edge.source_machine));
  }

  return [...sections.values()];
}

/**
 * One named export market: a linked country XOR a plain-text label ("Europe").
 * The unknown-market row — the bottom rung of the row's target ladder — names
 * no market and so produces no view; the row's *existence* still counts as
 * "built for export", which the section carries on its own.
 */
export interface ModelExportMarketView {
  /** The destination country; `public_id` is its location_path for the `/locations/...` link. */
  location: EntityRef | null;
  /** Free-text market descriptor when the market is not a country; rendered unlinked. */
  label: string;
}

/**
 * The export-edition display section: the domestic original and/or the named
 * markets behind the Exports.md sentence, "This model is the export version of
 * [other model], built for export to [market(s)]." Each half is optional —
 * whichever facts exist are the ones the sentence states.
 */
export interface ModelExportEditionSection {
  heading: string;
  /** The domestic original, or `null` when it is unknown. */
  original: ModelLineageLinkView | null;
  /** The named markets; empty when the only market row is the unknown-market one. */
  markets: ModelExportMarketView[];
}

/**
 * The model's export-edition facts as one display section, or `null` when it
 * has none — no `export_edition_of` and no market rows. Rendered by the same
 * surfaces as {@link modelLineageSections}, after the lineage and edge
 * sections. An unknown-market row yields a section with no `original` and no
 * `markets`: the assertion "built for export" with nothing further to say.
 */
export function modelExportEditionSection(
  model: ModelDetailSchema,
): ModelExportEditionSection | null {
  const original = model.export_edition_of ?? null;
  const rows = model.export_markets ?? [];
  if (!original && rows.length === 0) return null;
  return {
    heading: 'Export Edition',
    original: original ? toModelLinkView(original, modelSubject(model)) : null,
    markets: rows
      .filter((row) => row.target_location || row.target_label)
      .map((row) => ({
        location: row.target_location ?? null,
        label: row.target_label ?? '',
      })),
  };
}

/**
 * Whether `model` has anything for the related-models surfaces to show:
 * lineage relations, relationship edges or export-edition facts. Gates the
 * mobile Related Models accordion on both the model and single-model title
 * pages, so a new section kind is added to the gate once, here.
 */
export function hasModelRelationshipContent(model: ModelDetailSchema): boolean {
  return (
    modelLineageSections(model).length > 0 ||
    modelEdgeSections(model).length > 0 ||
    modelExportEditionSection(model) !== null
  );
}
