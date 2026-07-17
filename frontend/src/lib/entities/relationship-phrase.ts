/**
 * Reader-facing phrasing for model relationships — the single source both the
 * editor rows and the viewing surfaces render from, so "Bootleg of Galaxie"
 * reads identically everywhere. Typed against the generated schema unions, so
 * a new backend enum value fails the build here instead of rendering wrong.
 */

import type { CrossTitleLinkSchema, ModelRef, ModelRelationshipInputSchema } from '$lib/api/schema';

/** The three edge types, derived from the wire union (never redeclared). */
export type EdgeKind = ModelRelationshipInputSchema['relationship_type'];

/** Relations that can appear on a cross-title lineage line — the edge kinds plus the remake lineage FK; derived from the wire union. */
export type CrossTitleRelation = CrossTitleLinkSchema['relation'];

/** Authorization status, derived from the wire union. */
export type LicenseStatus = NonNullable<ModelRelationshipInputSchema['license_status']>;

/** Every relationship kind the editor presents — the edges plus the two scalar lineage FKs. */
export type RelationshipKind = EdgeKind | 'variant' | 'remake';

/**
 * The lead-in phrase per (kind, license). "Bootleg" is the domain word for an
 * unlicensed copy — the one cell with its own name; every other cell composes
 * the license adjective onto the kind noun. Unknown license renders bare
 * (no "possibly licensed" hedging — absence of the axis is the statement).
 */
const EDGE_LEADS: Record<EdgeKind, Record<LicenseStatus, string>> = {
  copy: {
    unknown: 'Copy of',
    licensed: 'Licensed copy of',
    unlicensed: 'Bootleg of',
  },
  conversion: {
    unknown: 'Conversion of',
    licensed: 'Licensed conversion of',
    unlicensed: 'Unlicensed conversion of',
  },
  conversion_kit: {
    unknown: 'Conversion kit for',
    licensed: 'Licensed conversion kit for',
    unlicensed: 'Unlicensed conversion kit for',
  },
};

/**
 * The lead-in phrase for one relationship row, e.g. "Bootleg of" /
 * "Variant of". The caller appends the target (linked machine or plain label).
 */
export function relationshipLead(kind: RelationshipKind, license: LicenseStatus): string {
  if (kind === 'variant') return 'Variant of';
  if (kind === 'remake') return 'Remake of';
  return EDGE_LEADS[kind][license];
}

/**
 * Explanatory preface shown above an outbound edge section's targets, in the
 * style of the legacy lineage notes ("This game is a remake of:"). Each is a
 * sentence the target list completes, so it must end with a colon.
 */
const EDGE_NOTES: Record<EdgeKind, Record<LicenseStatus, string>> = {
  copy: {
    unknown: 'This game reproduces the design of:',
    licensed: 'This game is an officially licensed copy of:',
    unlicensed: 'This game is an unauthorized copy of:',
  },
  conversion: {
    unknown: 'This game was rebuilt from the hardware of:',
    licensed: 'This game was rebuilt, under license, from the hardware of:',
    unlicensed: 'This game was rebuilt, without authorization, from the hardware of:',
  },
  conversion_kit: {
    unknown: 'This game is a kit that converts:',
    licensed: 'This game is an officially licensed kit that converts:',
    unlicensed: 'This game is an unauthorized kit that converts:',
  },
};

/** The explanatory preface for an outbound edge section of one (kind, license). */
export function relationshipNote(kind: EdgeKind, license: LicenseStatus): string {
  return EDGE_NOTES[kind][license];
}

/**
 * Heading for the inbound side of an edge — the models that copy, convert or
 * kit-target the subject. Plural nouns mirroring the legacy reverse-list
 * headings ("Bootlegs", "Conversions"); unknown license renders bare, like
 * the leads.
 */
const EDGE_INBOUND_HEADINGS: Record<EdgeKind, Record<LicenseStatus, string>> = {
  copy: {
    unknown: 'Copies',
    licensed: 'Licensed Copies',
    unlicensed: 'Bootlegs',
  },
  conversion: {
    unknown: 'Conversions',
    licensed: 'Licensed Conversions',
    unlicensed: 'Unlicensed Conversions',
  },
  conversion_kit: {
    unknown: 'Conversion Kits',
    licensed: 'Licensed Conversion Kits',
    unlicensed: 'Unlicensed Conversion Kits',
  },
};

/** The inbound-side heading for edges of one (kind, license), e.g. "Bootlegs". */
export function inboundRelationshipHeading(kind: EdgeKind, license: LicenseStatus): string {
  return EDGE_INBOUND_HEADINGS[kind][license];
}

/**
 * Explanatory preface for an inbound edge section, in the style of the legacy
 * reverse-list notes ("Unauthorized copies of this game:").
 */
const EDGE_INBOUND_NOTES: Record<EdgeKind, Record<LicenseStatus, string>> = {
  copy: {
    unknown: "Games that reproduce this game's design:",
    licensed: 'Officially licensed copies of this game:',
    unlicensed: 'Unauthorized copies of this game:',
  },
  conversion: {
    unknown: "Different games rebuilt from this machine's hardware:",
    licensed: "Different games rebuilt, under license, from this machine's hardware:",
    unlicensed: "Different games rebuilt, without authorization, from this machine's hardware:",
  },
  conversion_kit: {
    unknown: 'Kits that convert this machine into a different game:',
    licensed: 'Officially licensed kits that convert this machine into a different game:',
    unlicensed: 'Unauthorized kits that convert this machine into a different game:',
  },
};

/** The explanatory preface for an inbound edge section of one (kind, license). */
export function inboundRelationshipNote(kind: EdgeKind, license: LicenseStatus): string {
  return EDGE_INBOUND_NOTES[kind][license];
}

/**
 * Sentence form of a lead phrase, for lines with an explicit subject — the
 * title page's cross-title lineage: "Bootleg of" → "is a bootleg of",
 * "Unlicensed conversion of" → "is an unlicensed conversion of",
 * "Remake of" → "is a remake of".
 */
export function relationshipSentence(kind: CrossTitleRelation, license: LicenseStatus): string {
  const lead = relationshipLead(kind === 'remake_of' ? 'remake' : kind, license);
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
