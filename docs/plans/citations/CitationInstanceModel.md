# Citation Instance Model

Future-facing plan for the next citation model migration. This consolidates the target shape from [CitationUrlModel.md](CitationUrlModel.md), [CitationModelUnification.md](CitationModelUnification.md), and the durable conclusions from [CitationSystemAudit.md](CitationSystemAudit.md). The older docs remain in place for now, but this is the document to use when planning the migration.

## Goal

Make `CitationInstance` the structured reference object for both field edits and inline prose citations.

Today the citation system already has the right source-side split: `CitationSource` is the reusable work or evidence object, `CitationSourceLink` is a way to inspect that source, and `CitationInstance` is one use of the source. The missing piece is that the per-use evidence still leaks through other fields: consulted URLs live on source links, verbatim quotes are smuggled into `ChangeSet.note`, and edit-level citations are fanned out across claims instead of being owned by the edit that used them.

The target model makes one reference row carry the per-use evidence:

```text
CitationInstance
  source: CitationSource        required
  locator: string               optional
  quote: string                 optional verbatim excerpt
  access_url: URL               optional URL actually consulted
  owner: ChangeSet or Claim     exactly one
```

This keeps source identity shared while making the evidence attached to a specific edit or inline marker explicit.

## Current Problem

The current model has three competing text/evidence channels:

- `ChangeSet.note` is shown as an edit rationale, but data patches often use it to store the supporting quote.
- `Claim.citation` is a free-text ingest-only citation field that the interactive editor does not set.
- `CitationInstance` points at a structured source and locator, but has no quote, no access URL, and no changeset owner.

That split makes citation behavior harder to explain and harder to migrate. A structured field edit can have a citation, but internally the code clones the same `CitationInstance` across changed claims. Inline prose footnotes can be minted with `claim=null`, which means they are not visible from edit-history paths that follow the claim FK. The authoring UI tells contributors to explain why they are editing, while patch authoring asks them to put evidence text in the same field.

The cleanup should make one distinction clear:

- `ChangeSet.note` is an optional edit summary about the act of editing.
- `CitationInstance` is the structured evidence reference.

## Target Model

### CitationInstance fields

`CitationInstance` keeps its name. It becomes the reference row, not just a source-plus-locator join.

Required:

- `citation_source`: the work or evidence object being cited.

Optional:

- `locator`: page, timestamp, section, fragment, or other within-source pointer.
- `quote`: verbatim excerpt from the source.
- `access_url`: the URL actually consulted for this use.

Ownership:

- `changeset`: set when the citation supports a structured field edit.
- `claim`: set when the citation is an inline prose footnote attached to a markdown claim.

Exactly one owner is set: `changeset` XOR `claim`.

The row should stay immutable after creation. Corrections mint a replacement citation instance through an ordinary edit instead of mutating history in place.

### Quote

`quote` is a typed verbatim excerpt, not a general note. It replaces the current pattern where data patches put source text into `note:` using prose like `<source> says "..."`.

Only exact source text belongs in `quote`. Editorial rationale, uncertainty, cleanup comments, and merge explanations stay in `ChangeSet.note`.

The source pointer is always required. The locator-or-quote requirement is source-type-aware:

- Fine-grained web page children are independently checkable from the source pointer and optional `access_url`; locator and quote can be blank.
- Coarse sources such as books and magazine issues should normally require a locator or quote to be useful.

The exact validation rule can be implemented at the form/service layer first, then tightened once existing data has been audited.

### Access URL

`access_url` is the URL actually consulted for this citation instance. It is per-use evidence, so it lives on `CitationInstance`, not on `CitationSource`.

This is distinct from identity URLs:

- Identity URL: where the source or page canonically lives; shared source-level fact.
- Access URL: the specific URL consulted for this claim; per-instance fact.
- Archive URL: future snapshot of the access URL; deferred.

For a normal web page, the identity URL and access URL are often the same. They must still be modeled separately because archive and mirror cases differ: a contributor may cite a Wayback URL as the consulted copy while the source identity remains the original page.

### Archive tier

The archive tier is deferred. Do not add `archive_url`, `archived_at`, URL status, dead-link sweeping, or Wayback submission in this migration.

Deferring archive is safe because `access_url` is the lower rung the archive tier hangs from later. A future archive migration can add archive fields to the same citation instance without reworking source identity.

Human-pasted archive URLs are still useful in v1: they can be stored as `access_url`. Recognition needs archive peeling before that becomes good UX, because a raw Wayback URL otherwise recognizes against `web.archive.org` instead of the embedded original page.

## Ownership Model

### Structured field edits

Editing granularity is the `ChangeSet`. One save creates one changeset and can carry one edit-level citation.

That citation should attach once to the `ChangeSet`, not be cloned onto every claim written by the save. Each claim reaches its edit-level evidence through `claim.changeset`.

This matches the existing UI discipline: a single citation panel applies to all fields changed in the save, and unrelated fields needing distinct evidence should be split into separate saves.

### Inline prose footnotes

Inline citations remain per-marker. A markdown marker points at one `CitationInstance`, and that instance is owned by the markdown claim containing the marker.

This fixes the current orphan behavior where inline footnotes can exist with `claim=null` and then disappear from history surfaces that follow claim ownership.

### Owner guard

The database should enforce the ownership invariant:

```text
(changeset_id IS NOT NULL AND claim_id IS NULL)
OR
(changeset_id IS NULL AND claim_id IS NOT NULL)
```

Use `PROTECT` for both FKs. A claim or changeset with citation history should not silently delete its evidence.

## URL Recognition Followups

`access_url` does not by itself solve URL recognition. The migration should leave room for these additive followups:

- Archive peeling: recognize Wayback and archive.today long-form URLs by extracting the embedded original URL while storing the pasted archive URL as `access_url`.
- Child identity URL normalization: recognize reusable web children through a normalized identity-URL table rather than exact raw `CitationSourceLink.url` matching.
- Child URL deduplication: prevent `http` vs `https`, trailing slash, and tracking-param variants from fragmenting into multiple children.

These followups belong near the recognizer pipeline, not in the ownership migration, unless the migration already creates the normalized identity URL table.

## Data Patch Shape

Patch authoring should stop using `note:` for source quotes.

Target shape:

```yaml
note: Optional edit summary, rarely needed
cite:
  url: https://example.com/source-page
  locator: Optional section or page
  quote: Exact quoted source text
  access_url: Optional consulted URL when different from the source identity URL
```

Scheme citations keep their scheme form and gain the same per-use fields:

```yaml
cite:
  source: ipdb:4443
  locator: Optional locator
  quote: Exact quoted source text
```

The migration does not need to backfill quotes out of old `note:` prose. That would be heuristic and likely wrong. Existing notes can remain edit summaries or historical text; new patches should write `quote:` explicitly once the field exists.

## Read And Write Surfaces

The migration affects these areas:

- Claim write path: stop fan-out cloning citation instances per claim; mint one changeset-owned citation for the edit-level citation.
- Inline citation path: mint claim-owned citation instances for markdown markers.
- Evidence/read helpers: collect changeset-owned citations for structured claims and claim-owned citations for inline prose.
- Description attribution: stop depending on `Claim.citation` free text once structured evidence is available.
- Editor UI: add a quote field to the citation panel and keep `note` labeled as edit summary.
- Data patch parsing: parse `quote:` and optional `access_url` inside `cite:`.
- API schemas: expose `quote` and `access_url` wherever citation instances are rendered or created.

The quote UI is the largest frontend change. `access_url` is mostly a field addition once the backend can store it. Retiring `Claim.citation` is a model/read-path change more than a UI change.

## Migration Shape

This should be one planned migration cluster, not two unrelated migrations, because `access_url`, `quote`, ownership, and `Claim.citation` retirement all touch the meaning of `CitationInstance`.

Suggested phases:

1. Add nullable `quote`, nullable `access_url`, nullable `changeset`, and the owner constraint in a form that tolerates existing rows during backfill.
2. Backfill existing citation ownership where it is unambiguous.
3. Change the write paths to mint changeset-owned edit citations and claim-owned inline citations.
4. Change read paths and schemas to consume the new shape.
5. Stop writing `Claim.citation` and update patch authoring to use `cite.quote`.
6. Tighten constraints after existing rows and tests prove the new ownership rules.
7. Retire `Claim.citation` once no read path depends on it.

Backfill caution: mapping existing per-claim citation clones back to one changeset-level citation is not always provably correct. Prefer a conservative backfill that handles obvious cases and leaves ambiguous historical rows readable rather than inventing evidence relationships.

## Deferred

- Archive URL tier and archive-date/status machinery.
- Precise access dates for data patches. `created_at` is good enough for interactive access time but fabricated for rebuild-applied patches.
- Automatic quote extraction or quote backfill from old notes.
- Admin tooling for repairing orphaned or ambiguous historical citation instances.
- Normalized identity URL table, unless it is explicitly pulled into this migration.

## Open Questions

- Should the locator-or-quote rule for coarse sources be enforced server-side at first, or only surfaced as UI validation until existing data has been audited?
- What is the exact conservative backfill for current per-claim citation clones?
- Should `access_url` be accepted in the interactive UI immediately, or only stored through patch/import paths until archive peeling exists?
- Does the normalized identity URL table belong in this migration, or in the recognizer followup?
