/**
 * Reader-facing phrasing for model relationships — the single source both the
 * editor rows and the viewing surfaces render from, so "Bootleg of Galaxie"
 * reads identically everywhere. Typed against the generated schema unions, so
 * a new backend enum value fails the build here instead of rendering wrong.
 */

import type { ModelRef, ModelRelationshipInputSchema } from '$lib/api/schema';

/** The three edge types, derived from the wire union (never redeclared). */
export type EdgeKind = ModelRelationshipInputSchema['relationship_type'];

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
 * Display text for a machine target: "Galaxie (Gottlieb 1971)". The
 * parenthetical disambiguates same-named machines (a game and its copies
 * often share a name); either part may be missing.
 */
export function machineTargetText(ref: Pick<ModelRef, 'name' | 'year' | 'manufacturer'>): string {
  const qualifier = [ref.manufacturer?.name, ref.year].filter(Boolean).join(' ');
  return qualifier ? `${ref.name} (${qualifier})` : ref.name;
}
