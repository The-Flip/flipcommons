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
 *
 * Ordering is derived in two passes: the drafts below accumulate and sort, then
 * a freeze pass walks the ordered result assigning reference numbers, so the
 * page reads 1, 2, 3… top to bottom. A number cannot be known until the values
 * around it are ordered, which is why the exported shapes are built only in
 * that second pass, complete.
 */
import type {
  ClaimAttributionSchema,
  ClaimCitationSchema,
  ClaimSchema,
  ClaimValueSchema,
} from '$lib/api/schema';
import type { InlineCitation } from '$lib/components/markdown/citation-tooltip';

/** A marker with no inline position in the value's text — evidence attached to
 *  the claim rather than cited from it. Rendered as a trailing superscript. */
export interface FootnoteMarker {
  /** Reference number into `SourcesView.references`. */
  index: number;
  /** Citation-instance id, for the tooltip's `data-cite-id`. */
  id: number;
}

/** One distinct value within a slot, with everything that backs it. */
export interface ValueSupport {
  /** Canonical JSON form of the value — stable `{#each}` key within a slot. */
  key: string;
  /** Page-unique identity, for state the page keeps per value. Claim keys are
   *  unique within an entity, so pairing one with a value key is too. */
  uid: string;
  value: ClaimValueSchema;
  /** Whether the value is prose — a markdown field, the only kind whose text
   *  runs to paragraphs. Drives both the collapse and whether the value's own
   *  text can position a citation marker, so the two cannot disagree. */
  isProse: boolean;
  /** Distinct actors asserting this value, most recent assertion first. */
  supporters: ClaimAttributionSchema[];
  /** Reference numbers keyed by citation-instance slug, for the citations the
   *  value's own text positions with an inline `[[cite:slug]]` marker. Feeds
   *  `ChangeValue`, which renders them as superscripts in place. */
  citeIndexes: Map<string, number>;
  /** Reference number → citation-instance id, for the numbers this value cites
   *  *inline*. Deliberately excludes its footnote numbers: the marker renderer
   *  treats any bracketed number in the text as a marker, so a number the
   *  value never substituted must not be resolvable from stray prose.
   *  Footnote markers carry their own id and never go through that path. */
  citeIds: Map<number, number>;
  /** Markers with no inline position, ascending by reference number. */
  footnotes: FootnoteMarker[];
  /** Whether this value currently wins its slot. */
  isWinner: boolean;
}

/** One claim key — the set of values competing for a single resolved slot. */
export interface ClaimSlot {
  claimKey: string;
  /** The value that currently wins resolution for this slot. */
  winner: ValueSupport;
  /** Values that lost, newest-first. Empty unless sources disagree. */
  others: ValueSupport[];
}

/** One field of the entity and all the claims made about it. */
export interface FieldSupport {
  field: string;
  /** One entry for a scalar field; one per related row for a relationship field. */
  slots: ClaimSlot[];
}

/** The whole page: the field list plus the citations its entries reference. */
export interface SourcesView {
  fields: FieldSupport[];
  /** Every distinct citation on the page, in reference-number order. Carries
   *  its own `index`, so it satisfies `InlineCitation` and feeds both the
   *  reference list and the marker tooltip unchanged. */
  references: InlineCitation[];
  /** Every actor that asserted a claim, most recent contribution first. */
  contributors: ClaimAttributionSchema[];
}

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
 *  "A B" with no author keying the same as source "A" by author "B".
 *
 *  `slug` is deliberately out of the key: the same evidence reaches a claim
 *  both as an attached join row (no slug) and as an inline marker (slug), and
 *  those are one citation, listed once. */
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
interface ValueDraft {
  key: string;
  value: ClaimValueSchema;
  supporters: Map<string, ClaimAttributionSchema>;
  citations: Map<string, ClaimCitationSchema>;
  isWinner: boolean;
  latestAt: string;
}

/** One slot mid-build: its distinct values, ordered winner-first. */
interface SlotDraft extends Dated {
  claimKey: string;
  values: ValueDraft[];
}

/** One field mid-build: its slots, ordered. */
interface FieldDraft extends Dated {
  field: string;
  slots: SlotDraft[];
}

/** Distinct values of one slot, keyed by the canonical JSON of the value. */
type SlotAccumulator = Map<string, ValueDraft>;
/** One field's slots, keyed by claim key. */
type FieldAccumulator = Map<string, SlotAccumulator>;

function foldClaim(draft: ValueDraft, claim: ClaimSchema): void {
  keepLatestByActor(draft.supporters, claim.attribution);
  for (const citation of claim.citations) {
    const key = citationKey(citation);
    const seen = draft.citations.get(key);
    // Prefer the slug-bearing copy: only it can be placed inline, and the
    // attached copy of the same evidence carries no extra information.
    if (!seen || (seen.slug == null && citation.slug != null)) {
      draft.citations.set(key, citation);
    }
  }
  draft.isWinner ||= claim.is_winner;
  if (claim.attribution.created_at > draft.latestAt) draft.latestAt = claim.attribution.created_at;
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
    let draft = values.get(key);
    if (!draft) {
      draft = {
        key,
        value: claim.value,
        supporters: new Map(),
        citations: new Map(),
        isWinner: false,
        latestAt: claim.attribution.created_at,
      };
      values.set(key, draft);
    }

    foldClaim(draft, claim);
  }
  return byField;
}

/** Order one slot's values: the winner, then the values it displaced,
 *  newest-first. */
function draftSlot(claimKey: string, values: SlotAccumulator): SlotDraft {
  const ordered = [...values.values()].sort(
    (a, b) => Number(b.isWinner) - Number(a.isWinner) || byRecency(a, b),
  );
  return { claimKey, values: ordered, latestAt: latestOf(ordered) };
}

/** Order one field's slots, most recently claimed first. */
function draftField(field: string, slotMap: FieldAccumulator): FieldDraft {
  const slots = [...slotMap]
    .map(([claimKey, values]) => draftSlot(claimKey, values))
    .sort(byRecency);
  return { field, slots, latestAt: latestOf(slots) };
}

/** Assigns each distinct citation its page-wide reference number on first
 *  sight, in the reading order the freeze pass walks. */
class ReferenceNumbering {
  readonly references: InlineCitation[] = [];
  readonly #numbers = new Map<string, number>();

  /** The 1-based number for *citation*, minting one if it is new. */
  numberFor(citation: ClaimCitationSchema): number {
    const key = citationKey(citation);
    let index = this.#numbers.get(key);
    if (index === undefined) {
      index = this.references.length + 1;
      // `links` is optional on the wire but required by InlineCitation, since
      // the tooltip and the reference entry both split it unconditionally.
      this.references.push({ ...citation, index, links: citation.links ?? [] });
      this.#numbers.set(key, index);
    }
    return index;
  }
}

/**
 * Freeze one ordered value draft, numbering its citations.
 *
 * A citation with a slug is positioned by an inline `[[cite:slug]]` marker in
 * the value's own text, so it goes to `citeIndexes` for in-place rendering;
 * one without is attached evidence with nowhere to sit, so it becomes a
 * trailing footnote. A markdown value is the only kind whose text carries
 * markers — anywhere else a slug-bearing citation has no marker to replace, so
 * it falls back to a footnote rather than vanishing.
 */
function freezeValue(
  draft: ValueDraft,
  claimKey: string,
  numbering: ReferenceNumbering,
): ValueSupport {
  const isProse = draft.value.display?.kind === 'markdown';
  const citeIndexes = new Map<string, number>();
  const citeIds = new Map<number, number>();
  const footnotes: FootnoteMarker[] = [];
  for (const citation of draft.citations.values()) {
    const index = numbering.numberFor(citation);
    if (isProse && citation.slug != null) {
      citeIndexes.set(citation.slug, index);
      // Only a number this value actually cites inline goes in the lookup the
      // marker renderer consults, so a number it merely footnotes cannot be
      // resolved out of a literal "[3]" the prose happens to contain.
      citeIds.set(index, citation.id);
    } else {
      footnotes.push({ index, id: citation.id });
    }
  }
  return {
    key: draft.key,
    uid: `${claimKey} ${draft.key}`,
    value: draft.value,
    isProse,
    supporters: [...draft.supporters.values()].sort((a, b) =>
      newestFirst(a.created_at, b.created_at),
    ),
    citeIndexes,
    citeIds,
    // A citation first seen under an earlier field keeps its low number, so
    // sort — otherwise a value reads "6, 7, 8, 3".
    footnotes: footnotes.sort((a, b) => a.index - b.index),
    isWinner: draft.isWinner,
  };
}

function freezeSlot(draft: SlotDraft, numbering: ReferenceNumbering): ClaimSlot {
  // Every claim key has a winner (the backend marks one per key), so the head
  // of a winner-first ordering is it.
  const [winner, ...others] = draft.values.map((value) =>
    freezeValue(value, draft.claimKey, numbering),
  );
  return { claimKey: draft.claimKey, winner, others };
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
  const drafts = [...accumulate(sources)]
    .map(([field, slotMap]) => draftField(field, slotMap))
    .sort(byRecency);

  const numbering = new ReferenceNumbering();
  const fields = drafts.map((draft) => ({
    field: draft.field,
    slots: draft.slots.map((slot) => freezeSlot(slot, numbering)),
  }));

  return {
    fields,
    references: numbering.references,
    contributors: collectContributors(sources),
  };
}
