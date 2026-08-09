# Generating Patches with `patchkit`

`patchkit` is the shared Python helper for generating large curated **classification** patches — a population classified from source data, where each row needs a verbatim source quote. **When** to reach for it instead of hand-authoring native YAML is in [DataPatchAuthoring.md → Hand-authored or generated?](DataPatchAuthoring.md#hand-authored-or-generated). This doc is the workflow once you've decided to generate.

It exists because the scaffolding around a generated patch — YAML escaping, the guards, reading the campaign's analysis — is easy to re-derive slightly wrong in each session. Read this once and use `patchkit`.

## The shape: an analysis file and an emitter

A campaign is **two files** in flippatch's `campaigns/<patch>/`, and the split is the design:

```text
flippatch/
  patches/
    0181-bingo-years.yaml             # the shipped patch
  scripts/
    patchkit.py                       # the shared helper
  campaigns/
    0181-bingo-years/
      years.sql                       # the analysis: detect, classify, gate, extract quotes
      gen.py                          # the emitter: one view -> patch YAML
      README.md                       # the narrative: signal, totals, dead-end searches
```

**`<name>.sql` is where the thinking lives.** It is a DuckDB analysis file over the shared catalog foundation — see [scripts/analysis/README.md](../scripts/analysis/README.md) for the four-section shape and the runner. Candidate detection, the false-positive gate, the human-judgment lookups and the verbatim quote extraction all belong here, in SQL, next to the data they reason about. It ends in the `<prefix>_summary` / `<prefix>_checks` pair the runner gates on, so the campaign's invariants are executable rather than described.

Iterate on it with the runner, from the flippatch checkout:

```bash
F=campaigns/0181-bingo-years/years.sql
make analyze FILE=$F PREFIX=year               # watermark + summary, gated on checks
make analyze FILE=$F Q="FROM year_patch_rows;" # exactly what gen.py will emit
make analyze FILE=$F Q="FROM year_rejected;"   # what the gate held back, and why
```

**`gen.py` is a pure emitter.** It reads one view and turns each row into a claims entry. It holds no detection logic and issues no catalog queries of its own — if you find yourself filtering rows in Python, that predicate belongs in the analysis file, where the checks can see it.

```python
rows = pk.read_view(YEARS_SQL, "year_patch_rows", prefix="year")

entries = [
    pk.entry(
        f"model.{r['slug']}",
        cite={"ref": CDYN_URL, "quote": pk.clean_quote(r["quote"])},
        fields={"year": r["year"]},
    )
    for r in sorted(rows, key=lambda r: r["slug"])
]
pk.write_patch(PATCH_PATH, attribution="flipcommons-catalog", description="…", entries=entries)
```

`read_view` runs the analysis's checks **before** it yields a row, so a generator cannot emit a patch from an analysis whose detectors have gone dark. That gate matters because its absence is invisible: a patch built on a rotted regex is still perfectly well-formed YAML, and every gate downstream of the generator will pass it. `prefix` names the checks pair explicitly, since it routinely differs from the filename — `exports.sql` gates on `export_checks`, `features.sql` on `gpf_checks`.

The worked examples to copy are **`0177-exports`**, **`0178-gameplay-features`** and **`0181-bingo-years`**.

## `patchkit` API

`gen.py` puts flippatch's `scripts/` on `sys.path` (`sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))`) and imports `patchkit as pk`.

| function                                                                                                                                                                          | purpose                                                                            |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| `read_view(analysis, view, *, prefix)`                                                                                                                                            | rows of one view from the campaign's analysis file, gated on its checks            |
| `entry(ref, *, create, note, cite, cites, fields, description, tags, credits, relationships, model_relationship, export_market, changesets, remove, retract, commented, comment)` | one correctly-escaped `claims:` block                                              |
| `source_root(name, *, source_type, description, links)`                                                                                                                           | one `sources:` block entry — the website root a URL `cite:` nests under            |
| `write_patch(path, *, attribution, description, entries, sources)`                                                                                                                | the complete patch file                                                            |
| `render_patch(...)`                                                                                                                                                               | the same as text, without writing — for byte-comparing a regeneration              |
| `clean_quote(s)`                                                                                                                                                                  | the sanctioned quote normalization: smart quotes straightened, `…` spelled `[...]` |
| `clean_ipdb_quote(text, limit=240)`                                                                                                                                               | additionally strips IPDB's run-on header and `…: "<passage>` framing               |
| `yamlq` / `clean_text`                                                                                                                                                            | the escaper / the typography normalizer, if you need them directly                 |

**Escaping is solved — use it.** Notes and quotes go through `yamlq` (single-quoted YAML: literal except `'`, which doubles), which carries an excerpt's own double quotes and apostrophes alike, with no backslashes. Never `yaml.dump`, never `json.dumps` a note or a quote, never hand-roll it.

**Relationship members.** `entry(...)` takes `relationships={namespace: [members]}` (the general emitter; `tags=` is the `tag` shorthand) and `remove={namespace: [members]}`. Members are escaped, so string members for aliases and abbreviations are safe — `relationships={"manufacturer_alias": ["Stern Pinball", "Stern, Inc"]}`. A `gameplay_feature` member may carry a count as a one-key `{public_id: count}` mapping, and the two forms mix freely in one list.

**Guards that run at author time.** `entry()` enforces what it can see before a patch ever reaches ingest: within-entry inline-citation correspondence (every numeric `[[cite:N]]` marker has a `cites:` entry and vice versa), counted-member validity, and the export-market shape rules — including "a row with no target must be the model's only row", which ingest applies **silently** as an illegal mix, making this the only gate it has.

**Inline citations.** `entry(..., cites={"1": "ipdb:4443", "2": {"ref": …, "quote": …}})` emits the `cites:` map a `description` references as `[[cite:1]]` — see [DataPatches.md → Inline citations in descriptions](DataPatches.md#inline-citations-in-descriptions). The mapping form takes the same `{ref, archive, locator, quote}` keys as an entry-level `cite:`.

## Provenance in generated patches

The attribution, cite and quote rules are canonical in [DataPatchAuthoring.md → Authoring a good patch](DataPatchAuthoring.md#authoring-a-good-patch). One consequence specific to generated patches: vocabulary and its assignment can share one file, since a patch may reference an entity it creates **earlier in the same file**. Emit the vocabulary entries above the assignments that reference them, in topological order where the terms form a tree. Split vocabulary into an earlier patch only when the two genuinely need different attributions.

## The audit trail

The campaign's `README.md` carries what SQL cannot: the signal you used, the totals (quoted from `<prefix>_summary`, never hand-counted), the judgment calls, and the **dead-end searches** — proving a term is absent from the sources is what justifies the signal you did use. Prose is the right home for dead ends; don't build a generator for them.

Human judgment that the analysis depends on goes in its Reference section as a lookup table, not in `gen.py`, so the checks can hold it honest — see [scripts/analysis/README.md → Making manual judgment checkable](../scripts/analysis/README.md#making-manual-judgment-checkable-optional).

## Validate

Iterate behind a localhost snapshot, then verify and hand off — the full loop is in [DataPatchAuthoring.md → Validation process](DataPatchAuthoring.md#validation-process).

Generator-specific additions:

- A curated patch classifies a whole **population**, so after applying confirm the population landed — the distribution across buckets looks right and the counts match `<prefix>_summary` — not just that one spot-checked entity resolved.
- **Every quote is a proposal until `make verify-quote-verbatim` passes.** That gate checks each span against the evidence corpus independently of your extraction — **except a PDF's**, which it reports `SKIP-PDF` and leaves to you (see [DataPatchAuthoring.md → PDF citations](DataPatchAuthoring.md#pdf-citations)). A generator emitting PDF-sourced quotes therefore has no machine backstop: transcribe from the rendered sheet, and put whatever invariants you can in the analysis file instead.
- **A patch already in `patches/` is immutable.** Localhost may be far ahead of production, and nothing in the repo records what production has ingested — only the user knows. If an existing patch looks worth regenerating, raise it and let them decide.

## Gotchas (learned the hard way)

- **Keyword matches catch cross-references.** A note about _Bally Derby_ makes "Skill Derby" look like a gun game. Read the matched sentence; keep an explicit exclude list in the analysis's Reference section for the misses.
- **The signal can have false positives.** A note saying "not a pinball" may be about a _different_ game it cross-references. When unsure, leave the field unset — an honest unknown beats a wrong fact.
- **Anchor every free-text detector.** A rotted regex or a renamed column zeroes a whole detector with no error, and a row-level invariant cannot see a set silently shrink. An anchor check asserting a known example still triggers is the only thing that catches it.
- **Cut the quote from the raw source text, not from a parsed segment.** Then it is verbatim by construction and `verify-quote-verbatim` passes by construction too.
- **Joined spans must appear in source order.** `verify-quote-verbatim` checks each `[...]`-joined span separately and requires the order the source uses, so a row matching several patterns follows its own source text, not your feature ordering. Dedupe repeated spans — one phrase asserting two facts would otherwise read as out of order.
- **Values are JSON-shaped; YAML coercion is off.** `patchkit._scalar` handles this — a bare `1996-01-01` stays a string, `no` stays `"no"`.
- **`except A, B:` is valid Python 3** and ruff's preferred style — don't parenthesize (a project-wide rule, relevant if your generator catches exceptions).
