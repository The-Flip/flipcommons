# How to Review a Data Patch

## Understand data patches first

1. [DataPatches.md](DataPatches.md) — what a patch is and how it applies.
2. [DataPatchAuthoring.md](DataPatchAuthoring.md) — the rules a good patch follows. Your job is to confirm they were followed.

## The job is editorial

Verify the **content**: that the values set for each entity are accurate and carry correct notes, citations and attribution, and follows the rules in [DataPatchAuthoring.md](DataPatchAuthoring.md).

Do NOT check syntax, lint or run tests.

## How to verify

For generated patches, work from the patch's own uncommitted artifacts (the worksheet, README, generator). Hand-authored patches usually will not have a `patches/authoring/NNNN-*` directory; for those, work from the patch file itself. Subject to the authoring rules, every value should be backed by its claim `note:` or `cite:`, so you shouldn't need to re-fetch any page. If you think you do, that's a flaw in the authoring process: report it to the user rather than fetching.

When you need to read deeper:

- **Cited web pages** — the SQLite cache in pinexplore at `~/dev/pinexplore/ingest_sources/web/cache.sqlite` (see `~/dev/pinexplore/docs/WebCache.md`). Assume a verbatim citation in an artifact is faithfully verbatim.
- **IPDB / OPDB data** — pinexplore's DuckDB analytics database via the DuckDB CLI (IPDB free-text notes, OPDB keywords).

## Checklist — confirm the Authoring rules hold

Check each against [DataPatchAuthoring.md](DataPatchAuthoring.md):

- **Attribution** — the right source owns each claim; a retraction sits with whoever made the original claim; a narrative description uses its `flipcommons-ai-desc-<entity-type>` source.
- **Values accurate** — each asserted value matches the cited evidence.
- **Notes verbatim** — `note:` quotes the source faithfully (omissions marked `[...]`, non-ASCII preserved).
- **Citations support the claim** — the `cite:` record actually states the asserted fact, and each inline `[[cite:…]]` footnote in a description has a source that supports its sentence.
- **Descriptions** — follow [Record descriptions](DataPatchAuthoring.md#record-descriptions): factual, supported, not a title dump, no phrasing that will date.
