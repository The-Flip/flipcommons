/**
 * Shapes the Sources page: one entry per claim field, each listing the
 * distinct values asserted for it and who/what backs each one.
 *
 * The unit of competition is the claim's `claim_key`, which identifies the slot
 * a claim contends for: composite for a relationship member, so `theme` holding
 * four themes is four uncontested slots rather than a four-way conflict, and
 * equal to the field name for a direct field, so its rival values contend.
 * Within a slot, claims asserting the same value are consolidated into one
 * entry whose supporters and citations are pooled across every actor that
 * asserted it.
 */
import type {
  ClaimAttributionSchema,
  ClaimCitationSchema,
  ClaimSchema,
  ClaimValueSchema,
} from '$lib/api/schema';

/** A deduped citation paired with its identity key, so the numbering pass
 *  reuses the key `accumulate` already derived rather than rebuilding it. */
interface KeyedCitation {
  key: string;
  citation: ClaimCitationSchema;
}

/** One distinct value within a slot, with everything that backs it. */
export interface ValueSupport {
  /** Canonical JSON form of the value — stable `{#each}` key within a slot. */
  key: string;
  value: ClaimValueSchema;
  /** Distinct actors asserting this value, most recent assertion first. */
  supporters: ClaimAttributionSchema[];
  /** Ascending 1-based reference numbers into `SourcesView.references` — what
   *  the page renders as footnote markers. */
  citationNumbers: number[];
  /** Whether this value currently wins its slot. */
  isWinner: boolean;
  /** Internal: newest assertion of this value; the sort key for slots and fields. */
  latestAt: string;
  /** Internal: the deduped citations backing this value. Consumed by
   *  `numberCitations` to fill `citationNumbers`; the page renders bodies from
   *  `SourcesView.references`, never from here. */
  citationEntries: KeyedCitation[];
}

/** One claim key — the set of values competing for a single resolved slot. */
export interface ClaimSlot {
  claimKey: string;
  /** The value that currently wins resolution for this slot. */
  winner: ValueSupport;
  /** Values that lost, newest-first. Empty unless sources disagree. */
  others: ValueSupport[];
  /** Internal: sort key. */
  latestAt: string;
}

/**
 * How well-attested a field is, which drives its sort bucket: `contested`
 * (sources disagree) sorts above `corroborated` (more than one actor backs
 * some value) above `single` (every value rests on one actor).
 */
export type FieldSupportKind = 'contested' | 'corroborated' | 'single';

/** One field of the entity and all the claims made about it. */
export interface FieldSupport {
  field: string;
  /** One entry for a scalar field; one per related row for a relationship field. */
  slots: ClaimSlot[];
  kind: FieldSupportKind;
  /** Internal: sort key. */
  latestAt: string;
}

/** The whole page: the field list plus the citations its entries reference. */
export interface SourcesView {
  fields: FieldSupport[];
  /** Every distinct citation on the page, in reference-number order. */
  references: ClaimCitationSchema[];
  /** Every actor that asserted a claim, most recent contribution first. */
  contributors: ClaimAttributionSchema[];
}

const KIND_ORDER: Record<FieldSupportKind, number> = {
  contested: 0,
  corroborated: 1,
  single: 2,
};

/** Anything carrying the timestamp of its most recent assertion. */
interface Dated {
  latestAt: string;
}

/** Newest-first over ISO 8601 timestamps, which order correctly as plain
 *  strings — `localeCompare` would apply collation rules irrelevant here. */
function newestFirst(a: string, b: string): number {
  return a < b ? 1 : a > b ? -1 : 0;
}

/** Newest-first over anything carrying its most recent assertion. */
function byRecency(a: Dated, b: Dated): number {
  return newestFirst(a.latestAt, b.latestAt);
}

/** The latest `latestAt` across *items*, or `''` when there are none. */
function latestOf(items: readonly Dated[]): string {
  return items.reduce((max, item) => (item.latestAt > max ? item.latestAt : max), '');
}

/** A slot's values in display order: the winner, then everything it displaced. */
function slotValues(slot: ClaimSlot): ValueSupport[] {
  return [slot.winner, ...slot.others];
}

/** Identity of an actor, so the same source asserting twice counts once. */
function actorKey(attribution: ClaimAttributionSchema): string {
  const author = attribution.author;
  return author.kind === 'source' ? `source:${author.name}` : `user:${author.username}`;
}

/** Record *attribution* against its actor, keeping whichever assertion is newer. */
function keepLatestByActor(
  byActor: Map<string, ClaimAttributionSchema>,
  attribution: ClaimAttributionSchema,
): void {
  const key = actorKey(attribution);
  const seen = byActor.get(key);
  if (!seen || attribution.created_at > seen.created_at) byActor.set(key, attribution);
}

/** Identity of a citation, so the same evidence pooled twice counts once.
 *
 *  JSON rather than a joined string: the array encoding is injective, so no
 *  separator has to be chosen that the fields themselves cannot contain.
 *  Joining on a printable character would let neighbours collide — source
 *  "A B" with no author keying the same as source "A" by author "B". */
function citationKey(citation: ClaimCitationSchema): string {
  return JSON.stringify([
    citation.source_name,
    citation.author,
    citation.year ?? '',
    citation.locator,
    citation.quote,
  ]);
}

/** Mutable accumulator for one distinct value while claims are folded in. */
interface ValueAccumulator {
  key: string;
  value: ClaimValueSchema;
  supporters: Map<string, ClaimAttributionSchema>;
  citations: Map<string, ClaimCitationSchema>;
  isWinner: boolean;
  latestAt: string;
}

/** Distinct values of one slot, keyed by the canonical JSON of the value. */
type SlotAccumulator = Map<string, ValueAccumulator>;
/** One field's slots, keyed by claim key. */
type FieldAccumulator = Map<string, SlotAccumulator>;

function foldClaim(acc: ValueAccumulator, claim: ClaimSchema): void {
  keepLatestByActor(acc.supporters, claim.attribution);
  for (const citation of claim.citations) {
    const key = citationKey(citation);
    if (!acc.citations.has(key)) acc.citations.set(key, citation);
  }
  acc.isWinner ||= claim.is_winner;
  if (claim.attribution.created_at > acc.latestAt) acc.latestAt = claim.attribution.created_at;
}

/** Bucket every claim by field, then slot, then distinct value. */
function accumulate(sources: ClaimSchema[]): Map<string, FieldAccumulator> {
  const byField = new Map<string, FieldAccumulator>();
  for (const claim of sources) {
    let slots = byField.get(claim.field_name);
    if (!slots) {
      slots = new Map();
      byField.set(claim.field_name, slots);
    }

    let values = slots.get(claim.claim_key);
    if (!values) {
      values = new Map();
      slots.set(claim.claim_key, values);
    }

    const key = JSON.stringify(claim.value.raw ?? null);
    let acc = values.get(key);
    if (!acc) {
      acc = {
        key,
        value: claim.value,
        supporters: new Map(),
        citations: new Map(),
        isWinner: false,
        latestAt: claim.attribution.created_at,
      };
      values.set(key, acc);
    }

    foldClaim(acc, claim);
  }
  return byField;
}

/** Freeze one slot's accumulated values into display order: winner, then the
 *  values it displaced, newest-first. */
function buildSlot(claimKey: string, values: SlotAccumulator): ClaimSlot {
  const ordered: ValueSupport[] = [...values.values()]
    .map((acc) => ({
      key: acc.key,
      value: acc.value,
      supporters: [...acc.supporters.values()].sort((a, b) =>
        newestFirst(a.created_at, b.created_at),
      ),
      citationNumbers: [],
      isWinner: acc.isWinner,
      latestAt: acc.latestAt,
      // Carries the map's keys forward so numbering need not re-derive them.
      citationEntries: [...acc.citations].map(([key, citation]) => ({ key, citation })),
    }))
    .sort((a, b) => Number(b.isWinner) - Number(a.isWinner) || byRecency(a, b));
  // Every claim key has a winner (the backend marks one per key), so the head
  // of a winner-first ordering is it.
  const [winner, ...others] = ordered;
  return { claimKey, winner, others, latestAt: latestOf(ordered) };
}

/** Freeze one field's slots and classify how well-attested it is. */
function buildField(field: string, slotMap: FieldAccumulator): FieldSupport {
  const slots = [...slotMap]
    .map(([claimKey, values]) => buildSlot(claimKey, values))
    .sort((a, b) => Number(b.others.length > 0) - Number(a.others.length > 0) || byRecency(a, b));

  const kind: FieldSupportKind = slots.some((slot) => slot.others.length > 0)
    ? 'contested'
    : slots.some((slot) => slotValues(slot).some((value) => value.supporters.length > 1))
      ? 'corroborated'
      : 'single';
  return { field, slots, kind, latestAt: latestOf(slots) };
}

/**
 * Number every citation in reading order and collect the reference list.
 *
 * Runs after the fields are ordered so the page reads 1, 2, 3… top to bottom,
 * and writes each value's numbers back onto it — the numbers cannot be known
 * while the values are still being ordered.
 */
function numberCitations(fields: FieldSupport[]): ClaimCitationSchema[] {
  const references: ClaimCitationSchema[] = [];
  const numbers = new Map<string, number>();
  for (const field of fields) {
    for (const slot of field.slots) {
      for (const value of slotValues(slot)) {
        for (const { key, citation } of value.citationEntries) {
          let index = numbers.get(key);
          if (index === undefined) {
            index = references.push(citation);
            numbers.set(key, index);
          }
          value.citationNumbers.push(index);
        }
        // A citation first seen under an earlier field keeps its low number, so
        // sort — otherwise a value reads "6, 7, 8, 3".
        value.citationNumbers.sort((a, b) => a - b);
      }
    }
  }
  return references;
}

/** Every actor that asserted a claim, most recent contribution first. */
function collectContributors(sources: ClaimSchema[]): ClaimAttributionSchema[] {
  const byActor = new Map<string, ClaimAttributionSchema>();
  for (const claim of sources) keepLatestByActor(byActor, claim.attribution);
  return [...byActor.values()].sort((a, b) => newestFirst(a.created_at, b.created_at));
}

/**
 * Group an entity's active claims into the Sources page view.
 *
 * `sources` may arrive in any order; every ordering below is derived here.
 */
export function buildSourcesView(sources: ClaimSchema[]): SourcesView {
  const fields = [...accumulate(sources)]
    .map(([field, slotMap]) => buildField(field, slotMap))
    .sort((a, b) => KIND_ORDER[a.kind] - KIND_ORDER[b.kind] || byRecency(a, b));

  return {
    fields,
    references: numberCitations(fields),
    contributors: collectContributors(sources),
  };
}
