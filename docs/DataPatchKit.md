# Generating Patches with `patchkit`

`patchkit` is the shared Python helper for generating large curated **classification** patches — a population tagged or classified from source data, where each row needs a live-value `expect:` guard and a verbatim source quote. **When** to reach for it instead of hand-authoring native YAML is in [DataPatchAuthoring.md → Hand-authored or generated?](DataPatchAuthoring.md#hand-authored-or-generated). This doc is the workflow once you've decided to generate.

It exists because several AI sessions each re-derived the same generator from scratch — and each reinvented YAML escaping, the `expect:` guard chooser and the review-doc scaffolding slightly differently, some subtly wrong. Read this once and use `patchkit`; don't re-derive it.

## The recipe

Every good curated patch session converges on these steps:

1. **Classify into in-script data** — buckets of `(ref, verbatim evidence)` literals. Human judgment is frozen as data, not prose.
2. **Pull live catalog values** for the `expect:` guards, then assert every ref resolved (fail loud on a typo or drift — never silently skip).
3. **Choose the guard** per row — `ipdb_id` when keyed on the IPDB record, else `year`, else `corporate_entity`.
4. **Emit YAML with `patchkit`** — never `yaml.dump`; never hand-roll escaping.
5. **Keep the audit trail** alongside — the editorial judgment lives in `classify.py` as data (`INCLUDE`/`FLAGGED`/`REJECTED` dicts with a reason on each row), the realized rows + extracted quotes land in `worksheet.csv`, and a short `README.md` narrates the signal, the totals and the dead-end searches (proving a term is absent is what justifies the signal you did use). Prose in the README is the right home for dead-ends — don't build a generator for it.
6. **Validate** on a localhost snapshot, then ship — see [Validate](#validate).

## Where the work lives

Authoring artifacts are committed in **pindata**, next to the patches they produce — not in `/tmp` or `~/.claude/plans`, which lose the audit trail:

```text
pindata/patches/
  0010-game-formats.yaml              # the shipped patch(es)
  0011-...
  authoring/
    patchkit.py                       # the shared helper (this workflow's library)
    0010-game-formats/                # one dir per patch set
      classify.py                     # (optional) pinexplore-side: DuckDB -> worksheet.csv; holds the judgment dicts
      xref_sweep.py                   # (optional) extra source sweeps
      worksheet.csv                   # classification interchange (the realized rows + quotes)
      gen.py                          # reads worksheet.csv + live DB -> the patch YAML
      README.md                       # the narrative: signal, totals, dead-end searches
```

`0010-game-formats/` is the **worked reference example** — copy its shape.

### Two stages (source text vs live guards)

Curated patches draw on two different databases, so split the work:

- **Classification + verbatim source text** comes from **pinexplore** (the DuckDB analysis DB: IPDB/OPDB notes, cross-source checks). Output a `worksheet.csv`.
- **`expect:` guards** must come from the **live flipcommons DB** (the serving catalog), because guards exist to catch drift against _it_. `gen.py` runs from the backend, reads the CSV, looks up live slugs/ids and emits the YAML.

`patchkit` itself is pure Python (no Django, stdlib only) so it imports on either side; the one Django line — the live lookup — stays in `gen.py`. On the pinexplore side, `classify.py` can import it too for the source-text helpers (`sentences`, `sentence_with`, `clean_ipdb_quote`) instead of re-deriving them — add the authoring dir to `sys.path` first, as `gen.py` does:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # the authoring/ dir
import patchkit as pk
```

## `patchkit` API

Import from the authoring dir (`gen.py` does `sys.path.insert(0, <authoring>)`).

| function                                                                                                                          | purpose                                                                                                 |
| --------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `guard(row, prefer=("ipdb_id","year","corporate_entity"))`                                                                        | most specific `expect:` dict from a live-values row; `{}` if none                                       |
| `check_resolved(requested, found)`                                                                                                | raise if any ref didn't resolve (typo/drift)                                                            |
| `sentences(text)` / `sentence_with(blob, needle)`                                                                                 | split source free text; pull the sentence containing a needle                                           |
| `clean_ipdb_quote(text, limit=240)`                                                                                               | normalize a quote's typography, strip the IPD header and `…: "<passage>` framing, truncate with `[...]` |
| `source_note(source, verbatim, tail="")`                                                                                          | build `IPDB says "<verbatim>"` (normalizes typography, preserves non-ASCII; mark omissions `[...]`)     |
| `entry(ref, *, create, expect, note, cite, cites, fields, description, tags, relationships, remove, retract, commented, comment)` | one correctly-escaped `claims:` block                                                                   |
| `write_patch(path, *, attribution, description, entries)`                                                                         | a complete patch file                                                                                   |
| `yamlq` / `clean_text`                                                                                                            | the escaper / the typography normalizer, if you need them directly                                      |

**Escaping is solved — use it.** Notes go through `yamlq` (single-quoted YAML: literal except `'`, which doubles). This carries both the double quotes in `... says "x"` and apostrophes, with no backslashes. Do **not** `json.dumps` notes.

**Relationship members.** `entry(...)` also takes `relationships={namespace: [members]}` (the general emitter; `tags=` is the `tag` shorthand) and `remove={namespace: [members]}`. Members are escaped, so string members for aliases / abbreviations are safe — e.g. `relationships={"manufacturer_alias": ["Stern Pinball", "Stern, Inc"]}` or `remove={"abbreviation": ["MedievalMadness"]}`. Alias values case-fold for identity; abbreviations are verbatim (see [DataPatchAuthoring.md → Aliases and abbreviations](DataPatchAuthoring.md#aliases-and-abbreviations)).

**Inline citations.** `entry(..., cites={"1": "ipdb:4443", "2": {"url": "…", "archive": "…"}})` emits a `cites:` map for the new inline footnotes a `description` references as `[[cite:1]]` / `[[cite:2]]` (see [DataPatches.md → Inline citations in descriptions](DataPatches.md#inline-citations-in-descriptions)). `entry()` runs the **within-entry marker ↔ map correspondence guard at author time** — every numeric-handle marker needs a `cites:` entry, every `cites:` key must be a numeric handle a marker references, a slug marker (`[[cite:bqntvkrs]]`, an existing citation) carries no entry — so a structural mistake raises a `ValueError` before the patch ships. It can't confirm a slug _resolves_ (that's the backend's job at apply), and the cross-entry disjoint-fields rule stays backend-only (`entry()` sees one entry at a time).

Minimal generator:

```python
import patchkit as pk
from apps.catalog.models import MachineModel  # after django.setup()

rows = list(csv.DictReader(open("worksheet.csv")))
ids = [int(r["ipdb_id"]) for r in rows]
live = {m["ipdb_id"]: m for m in MachineModel.objects.filter(ipdb_id__in=ids).values("slug", "ipdb_id")}
pk.check_resolved(ids, live)

entries = [
    pk.entry(
        f"model.{live[int(r['ipdb_id'])]['slug']}",
        expect=pk.guard(live[int(r["ipdb_id"])], prefer=("ipdb_id",)),
        note=pk.source_note("IPDB", r["quote"]),
        cite=f"ipdb:{r['cite_ipdb']}",
        fields={"game_format": r["format"]},
    )
    for r in rows
]
pk.write_patch("../../0010-game-formats.yaml", attribution="flipcommons-catalog", description="...", entries=entries)
```

## Provenance in generated patches

The attribution, cite-vs-guard and verbatim-note rules are canonical in [DataPatchAuthoring.md → Authoring a good patch](DataPatchAuthoring.md#authoring-a-good-patch). Two consequences specific to generated patches:

- Vocab and its assignment can share one file now — the derive case attributes both to `flipcommons-catalog` (the assignment carries `cite: ipdb:<id>`), and same-patch backward refs let the vocab entries sit above the assignments that reference them. Split vocab into an earlier file only when the two genuinely need different attributions. The historical 0009→0010/0011 `game_format` patches predate same-patch refs and split anyway (`0009-game-format-vocab.yaml` → `0010-game-formats.yaml`; see [DataPatchAuthoring.md → Create new vocabulary in a patch](DataPatchAuthoring.md#create-new-vocabulary-in-a-patch-not-the-seed)).
- `source_note` / `clean_text` enforce the verbatim-note shape for you — use them rather than hand-formatting `<Source> says "<quote>"`.

## Validate

Iterate behind a localhost snapshot, then verify and hand off — the full loop (snapshot/rollback, the per-row spot-check, the misleading-dry-run trap on references that span patch files, and the hand-off) is in [DataPatchAuthoring.md → Validation process](DataPatchAuthoring.md#validation-process).

Generator-specific addition: a curated patch classifies a whole **population**, so after applying confirm the population landed — the distribution across buckets looks right and the row counts match your worksheet — not just that one spot-checked entity resolved.

## Gotchas (learned the hard way)

- **Keyword matches catch cross-references.** "Skill Derby" matched `gun game` from a sentence about _Bally Derby_. Read the matched sentence; keep an explicit override/exclude map for the misses. Re-read every non-trivial assignment.
- **The signal can have false positives.** A note saying "not a pinball" may be about a _different_ game it cross-references; the listed game can be a real pinball. When unsure, leave the field null — an honest unknown beats a wrong fact.
- **Assert the extracted quote contains the keyword you classified on.** When you re-extract a quote by needle (`sentence_with`), a stale or loose needle can land on a sentence that never names the mechanism — 0011's `bagatelle` needle "came in two sizes" matched a sentence with no "bagatelle" in it. A one-line guard (`assert FORMAT_KEYWORD[fmt].search(quote)`) turns that into a loud failure at classify time instead of a wrong claim in the patch.
- **Sentence-splitting can sever an inner quotation.** A verbatim sentence with its own `"..."` can split at the period _inside_ the inner quote, leaving a dangling `"` in the note (`IPDB says "... follows: "Hit the ball.`). It's valid YAML but reads oddly. `clean_ipdb_quote` now strips the `…: "<passage>` framing for you (returning `Hit the ball.`); only an inner quotation without a colon introducer (e.g. `He said "...`) may still need a manual trim.
- **`except A, B:` is valid Python 3** and ruff's preferred style — don't parenthesize (a project-wide rule; relevant if your generator catches exceptions).
- **Values are JSON-shaped; YAML coercion is off.** `patchkit._scalar` handles this — bare `1996-01-01` would stay a string, `no` stays `"no"`.
