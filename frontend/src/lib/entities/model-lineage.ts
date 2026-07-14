/**
 * Single source of truth for the model↔model lineage relations and their
 * display copy. Every reader surface that shows lineage — the mobile model
 * relationships list, the desktop model sidebar and the single-model title
 * page — renders from this declaration, so a new relation is added once here
 * instead of in near-clone `{#if}` blocks per surface.
 *
 * `entity-meta.ts` only knows the forward FKs (`variant_of`, `converted_from`,
 * `remake_of`, `bootleg_of`, `licensed_build_of`) and carries no display copy, so the reverse lists
 * and the headings/notes are declared here. `model-lineage.test.ts` guards that
 * the forward set stays in sync with `ENTITY_META`, so a new backend
 * model↔model FK forces a descriptor here rather than silently going unshown.
 */
import type { EntityRef, ModelDetailSchema, ModelRef } from '$lib/api/schema';
import {
  inboundRelationshipHeading,
  inboundRelationshipNote,
  machineTargetText,
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
  | 'converted_from'
  | 'conversions'
  | 'remake_of'
  | 'remakes'
  | 'bootleg_of'
  | 'bootlegs'
  | 'licensed_build_of'
  | 'licensed_builds';

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
    heading: 'Parent Model',
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
    many: true,
    resolve: (m) => m.variant_siblings ?? [],
  },
  {
    key: 'converted_from',
    heading: 'Converted From',
    note: 'This game was rebuilt from the hardware of:',
    many: false,
    resolve: (m) => one(m.converted_from),
  },
  {
    key: 'conversions',
    heading: 'Conversions',
    note: "Different games rebuilt from this machine's hardware:",
    many: true,
    resolve: (m) => m.conversions ?? [],
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
    key: 'bootleg_of',
    heading: 'Bootleg Of',
    note: 'This game is an unauthorized copy of:',
    many: false,
    resolve: (m) => one(m.bootleg_of),
  },
  {
    key: 'bootlegs',
    heading: 'Bootlegs',
    note: 'Unauthorized copies of this game:',
    many: true,
    resolve: (m) => m.bootlegs ?? [],
  },
  {
    key: 'licensed_build_of',
    heading: 'Licensed Build Of',
    note: 'This game is an officially licensed build of:',
    many: false,
    resolve: (m) => one(m.licensed_build_of),
  },
  {
    key: 'licensed_builds',
    heading: 'Licensed Builds',
    note: 'Officially licensed builds of this game:',
    many: true,
    resolve: (m) => m.licensed_builds ?? [],
  },
];

/**
 * A resolved lineage link ready to render: identity plus the maker to show for
 * disambiguation (or `null` to omit it).
 */
export interface ModelLineageLinkView {
  name: string;
  public_id: string;
  year?: number | null;
  /**
   * Manufacturer to show (as a link to its page), or `null` when it matches the
   * subject's maker or is unknown. Same-named links (a game and the bootlegs
   * that copied its name) otherwise read as a relation to itself, since no
   * reader surface shows a maker; a *differing* maker is what disambiguates them.
   */
  manufacturer: EntityRef | null;
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
  const subjectManufacturer = model.manufacturer?.name ?? null;
  const sections: ModelLineageSection[] = [];
  for (const relation of MODEL_LINEAGE_RELATIONS) {
    const links = relation.resolve(model);
    if (links.length === 0) continue;
    sections.push({
      relation,
      links: links.map((link) => ({
        name: link.name,
        public_id: link.public_id,
        year: link.year,
        manufacturer:
          link.manufacturer && link.manufacturer.name !== subjectManufacturer
            ? link.manufacturer
            : null,
      })),
    });
  }
  return sections;
}

/**
 * Look up a single lineage relation by key, for surfaces that render a curated
 * subset (the single-model title page shows only `bootlegs`). Throws on an
 * unknown key so a typo fails loudly rather than rendering nothing.
 */
export function modelLineageRelation(key: ModelLineageKey): ModelLineageRelation {
  const relation = MODEL_LINEAGE_RELATIONS.find((r) => r.key === key);
  if (!relation) throw new Error(`Unknown model lineage relation: ${key}`);
  return relation;
}

/**
 * One rendered line of a relationship-edge section: a machine target (the
 * whole text links to the model page) XOR a plain-text label target, mirroring
 * the edge's own target XOR. Inbound sections put the *source* model here.
 */
export interface ModelEdgeTargetView {
  /** Linked machine, or `null` for a label target. `text` is the full display text ("Galaxie (Gottlieb 1971)"). */
  machine: { text: string; public_id: string } | null;
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

function machineTargetView(ref: ModelRef): ModelEdgeTargetView {
  return { machine: { text: machineTargetText(ref), public_id: ref.public_id }, label: '' };
}

/**
 * The model's relationship edges (copy / conversion / conversion kit) grouped
 * into display sections: outbound edges under their lead phrase
 * ("Conversion kit for" → one target line per edge), then inbound edges under
 * the plural heading ("Conversion Kits" → one source line per edge). Groups
 * follow the edges' payload order of first appearance. Rendered by the same
 * surfaces as {@link modelLineageSections}, after the lineage sections.
 */
export function modelEdgeSections(model: ModelDetailSchema): ModelEdgeSection[] {
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
        ? machineTargetView(edge.target_machine)
        : { machine: null, label: edge.target_label ?? '' },
    );
  }

  for (const edge of model.inbound_relationships ?? []) {
    const key = `inbound:${edge.relationship_type}:${edge.license_status}`;
    const heading = inboundRelationshipHeading(edge.relationship_type, edge.license_status);
    const note = inboundRelationshipNote(edge.relationship_type, edge.license_status);
    section(key, heading, note).targets.push(machineTargetView(edge.source_machine));
  }

  return [...sections.values()];
}
