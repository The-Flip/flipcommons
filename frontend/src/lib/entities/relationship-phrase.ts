/**
 * Reader-facing phrasing for model relationships — the single source both the
 * editor rows and the viewing surfaces render from, so "Bootleg of Galaxie"
 * reads identically everywhere. Typed against the generated schema unions, so
 * a new backend enum value fails the build here instead of rendering wrong.
 */

import type { CrossTitleLinkSchema, ModelRef, ModelRelationshipInputSchema } from '$lib/api/schema';

/** The edge types (copy / conversion / conversion kit / re-theme), derived from the wire union (never redeclared). */
export type EdgeKind = ModelRelationshipInputSchema['relationship_type'];

/** Relations that can appear on a cross-title lineage line — the edge kinds plus the remake lineage FK; derived from the wire union. */
export type CrossTitleRelation = CrossTitleLinkSchema['relation'];

/** Authorization status, derived from the wire union. */
export type LicenseStatus = NonNullable<ModelRelationshipInputSchema['license_status']>;

/** Every relationship kind the editor presents — the edges plus the three scalar lineage FKs. */
export type RelationshipKind = EdgeKind | 'variant' | 'remake' | 'export_edition';

/** All reader-facing copy for one (edge kind, license) cell. */
interface EdgePhrases {
  /** Lead-in phrase, e.g. "Bootleg of". The caller appends the target. */
  lead: string;
  /** Outbound preface above the targets; a sentence they complete, so it ends
   * with a colon ("This game reproduces the design of:"). */
  note: string;
  /** Inbound plural heading, e.g. "Bootlegs". */
  inboundHeading: string;
  /** Inbound preface above the sources; ends with a colon. */
  inboundNote: string;
}

/**
 * Every edge kind's reader copy, one object per (kind, license) — colocated so a
 * new kind's phrasing lands in one block instead of four parallel maps. "Bootleg"
 * is the domain word for an unlicensed copy — the one cell with its own name;
 * others compose the license adjective onto the kind noun. Unknown license
 * renders bare (no "possibly licensed" hedging — absence of the axis is the
 * statement).
 */
const EDGE_PHRASES: Record<EdgeKind, Record<LicenseStatus, EdgePhrases>> = {
  copy: {
    unknown: {
      lead: 'Copy of',
      note: 'This game reproduces the design of:',
      inboundHeading: 'Copies',
      inboundNote: "Games that reproduce this game's design:",
    },
    // "Authorized", not "licensed": in a pinball catalog "licensed" reads as
    // theme licensing first (Godzilla is a licensed theme), and it pairs with
    // the unlicensed cell's existing "unauthorized copy".
    licensed: {
      lead: 'Authorized copy of',
      note: 'This game is an authorized copy of:',
      inboundHeading: 'Authorized Copies',
      inboundNote: 'Authorized copies of this game:',
    },
    unlicensed: {
      lead: 'Bootleg of',
      note: 'This game is an unauthorized copy of:',
      inboundHeading: 'Bootlegs',
      inboundNote: 'Unauthorized copies of this game:',
    },
  },
  conversion: {
    unknown: {
      lead: 'Conversion of',
      note: 'This game was rebuilt from the hardware of:',
      inboundHeading: 'Conversions',
      inboundNote: "Different games rebuilt from this machine's hardware:",
    },
    licensed: {
      lead: 'Licensed conversion of',
      note: 'This game was rebuilt, under license, from the hardware of:',
      inboundHeading: 'Licensed Conversions',
      inboundNote: "Different games rebuilt, under license, from this machine's hardware:",
    },
    unlicensed: {
      lead: 'Unlicensed conversion of',
      note: 'This game was rebuilt, without authorization, from the hardware of:',
      inboundHeading: 'Unlicensed Conversions',
      inboundNote: "Different games rebuilt, without authorization, from this machine's hardware:",
    },
  },
  conversion_kit: {
    unknown: {
      lead: 'Conversion kit for',
      note: 'This game is a kit that converts:',
      inboundHeading: 'Conversion Kits',
      inboundNote: 'Kits that convert this machine into a different game:',
    },
    licensed: {
      lead: 'Licensed conversion kit for',
      note: 'This game is an officially licensed kit that converts:',
      inboundHeading: 'Licensed Conversion Kits',
      inboundNote: 'Officially licensed kits that convert this machine into a different game:',
    },
    unlicensed: {
      lead: 'Unlicensed conversion kit for',
      note: 'This game is an unauthorized kit that converts:',
      inboundHeading: 'Unlicensed Conversion Kits',
      inboundNote: 'Unauthorized kits that convert this machine into a different game:',
    },
  },
  // A re-theme keeps the donor's gameplay and re-skins its art and theme. The
  // license axis reads as official/unofficial here (recovering the old
  // `manufacturer-retheme` / `unofficial-retheme` tag vocabulary); the stored
  // value is still licensed/unlicensed.
  retheme: {
    unknown: {
      lead: 'Re-theme of',
      note: 'This game re-skins the art and theme of:',
      inboundHeading: 'Re-themes',
      inboundNote: 'Games that re-skin this one with new art and theme:',
    },
    licensed: {
      lead: 'Official re-theme of',
      note: 'This game is an official re-theme of:',
      inboundHeading: 'Official Re-themes',
      inboundNote: 'Official re-themes of this game:',
    },
    unlicensed: {
      lead: 'Unofficial re-theme of',
      note: 'This game is an unofficial re-theme of:',
      inboundHeading: 'Unofficial Re-themes',
      inboundNote: 'Unofficial re-themes of this game:',
    },
  },
};

/**
 * The lead-in phrase for one relationship row, e.g. "Bootleg of" /
 * "Variant of". The caller appends the target (linked machine or plain label).
 */
export function relationshipLead(kind: RelationshipKind, license: LicenseStatus): string {
  if (kind === 'variant') return 'Variant of';
  if (kind === 'remake') return 'Remake of';
  if (kind === 'export_edition') return 'Export edition of';
  return EDGE_PHRASES[kind][license].lead;
}

/** The explanatory preface for an outbound edge section of one (kind, license). */
export function relationshipNote(kind: EdgeKind, license: LicenseStatus): string {
  return EDGE_PHRASES[kind][license].note;
}

/** The inbound-side heading for edges of one (kind, license), e.g. "Bootlegs". */
export function inboundRelationshipHeading(kind: EdgeKind, license: LicenseStatus): string {
  return EDGE_PHRASES[kind][license].inboundHeading;
}

/** The explanatory preface for an inbound edge section of one (kind, license). */
export function inboundRelationshipNote(kind: EdgeKind, license: LicenseStatus): string {
  return EDGE_PHRASES[kind][license].inboundNote;
}

/**
 * Sentence form of a lead phrase, for lines with an explicit subject — the
 * title page's cross-title lineage: "Bootleg of" → "is a bootleg of",
 * "Unlicensed conversion of" → "is an unlicensed conversion of",
 * "Remake of" → "is a remake of".
 */
export function relationshipSentence(kind: CrossTitleRelation, license: LicenseStatus): string {
  const editorKind: RelationshipKind =
    kind === 'remake_of' ? 'remake' : kind === 'export_edition_of' ? 'export_edition' : kind;
  const lead = relationshipLead(editorKind, license);
  const phrase = lead.charAt(0).toLowerCase() + lead.slice(1);
  return `is ${/^[aeiou]/i.test(phrase) ? 'an' : 'a'} ${phrase}`;
}

/**
 * Display text for a machine target: "Galaxie (Gottlieb 1971)". The
 * parenthetical disambiguates same-named machines (a game and its copies
 * often share a name); either part may be missing.
 */
export function machineTargetText(ref: Pick<ModelRef, 'name' | 'year' | 'manufacturer'>): string {
  const qualifier = [ref.manufacturer?.name, ref.year].filter(Boolean).join(' ');
  return qualifier ? `${ref.name} (${qualifier})` : ref.name;
}
