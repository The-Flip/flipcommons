# Packaged Analytics

How to hand the Flipcommons DuckDB analytics layer to someone outside the project, such as The Flip museum, without them having to checkout and deal with all of the Flipcommons repo.

The motivating case is The Flip museum. They built a manufacturer timeline poster off our public API and hit the limits of a flat JSON dump (see [mfgtimeline.md](../the_flip/mfgtimeline.md)). They had to re-figure out all the relationships and build the relational model. The analytics layer would really help with this. It simplifies the product database into a set of views that represent the actual domain model.

However, today that analytics is only usable from inside the flipcommons project, which is a hassle to set up. This is a relatively quick and simple proposal to get that analytics out of the Flipcommons repo.

## Why The Flip will want this

The analytics database is a curated semantic layer rather than a mirror of the Django schema: every view respects soft-deletes, declares its grain, decodes foreign keys to stable slugs and states the specific way it would otherwise hand you a confident wrong answer. The first value on offer is not convenience; it is correctness.

Other benefits:

- **It is legible to an AI.** The relations and columns and inter-column relationships and reasoning traps to beware are extensively documented, so an AI pointed at the file reads what each relation means and which trap it carries instead of inferring intent from column names.
- **It includes IPDB and OPDB.** It includes the IPDB and OPDB corpus, attached to the correct records, making it very easy to analyze across the combined set.
- **It includes provenance.** Unlike the export API, this includes all the claims and citation data: which actor asserted a fact, whether it won the conflict, what external evidence was cited.

## The approach: a script that produces a bundle

A new `make analytics-bundle` command would assemble a gitignored directory on demand, containing exactly and only what a recipient needs and nothing that only makes sense inside of Flipcommons. We zip up the directory and send it to The Flip through any convenient channel.

```text
flipcommons-analytics/
  flipcommons-catalog.duckdb    # the browse snapshot, named for the recipient
  README.md                     # what is in here, the grain and liveness rules, how to ask it things
  reference/
    catalog.sql
    provenance.sql
    data_patches.sql
```

We already have an `analysis browse` command that produces the exact DuckDB snapshot needed: every public relation materialized as a real table, standalone, no SQLite attach, no path resolution, currently ~120 MB across 60 relations. Relation comments now survive materialization, so the tables carry their own one-line descriptions, making it easy for AIs and humans to reason about the data.

### Why to include the reference SQL

Column-level semantics are not in the DuckDB snapshot, because they never existed as comments. Instead, the way the analytics foundation documents this for AI and human consumers is putting one-liners in `COMMENT ON VIEW` and the substantial material in the `═══` block comments in the SQL text — the grain, the liveness rule, and for each view the specific way it will hand you a plausible wrong answer. None of that is carryable as a database comment today, in particular because the documentation often spans multiple columns.

## Why a private bundle is acceptable

The public export API is license-gated per field: `description.attribution` and `image_attribution` carry the license and source for reusable text and images, and the ingested third-party free-text — `ipdb_notes`, `ipdb_notable_features`, `opdb_features`, raw `extra_data` — is deliberately not republished there. The analytics layer carries that free-text, so the bundle is not a thing to put behind a public URL.

For The Flip specifically that objection does not bite, because we're the same organization. They have access to the same information through other channels.

## Properties worth knowing

- **The artifact self-dates.** `analysis_context` is a view, so it materializes into the snapshot: DuckDB version, live model count, migration point, latest successful data patch with its fingerprint, latest changeset. A recipient can tell one bundle from the next without us tracking what we sent.
- **Refresh is a rebuild.** `browse` replaces its output atomically on every run, so there is no incremental-update story to design and no stale-partial state to worry about.
- **The reference SQL is already public.** flipcommons is a public repository, so including those files grants nothing new — it saves the recipient from needing to know that.

## README.md

The existing `script/analysis/README.md` has a lot of project-specific information that we don't want to include, but also a lot of very useful information about how to reason about the data, what the data is semantically. We shall NOT duplicate this information, so we have to figure out how to structure this.

One idea would be extracting the 'how to reason' info into a `Reasoning.md`. Audience-neutral, no checkout assumed. The bundle would ship that verbatim and add its own `README.md`.

Extracting the info into a `Reasoning.md` wouldn't be fully straightforward. A naive move leaves project-specific tails inside otherwise neutral prose. Examples:

- "read the Django model before concluding otherwise, then promote it" links to EDITING.md and assumes you can change the foundation
- "Found a phrasing the catalog lacks? Add it with a data patch, not a lookup table in your analysis"
- "What our own patches did" is framed around authoring campaigns in flippatch
