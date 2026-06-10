# Authoring Data Patches (the workflow)

[DataPatches.md](DataPatches.md) defines the patch **file format** and how patches
are applied. This doc is the **authoring workflow** for non-trivial, curated
patches — the repeatable recipe, the shared `patchkit` helper, where the work
lives, and how to validate before shipping.

It exists because several AI sessions each re-derived the same generator from
scratch — and each reinvented YAML escaping, the `expect:` guard chooser and the
review-doc scaffolding slightly differently, some subtly wrong. Read this once and
use `patchkit`; don't re-derive it.

## When to use this

- **A handful of edits** → hand-write the YAML against [DataPatches.md](DataPatches.md). Skip the machinery.
- **Dozens of curated rows** (a population tagged/classified from source data) → use this workflow: a script holds the classification, `patchkit` emits the YAML, and a worksheet records the editorial judgment.

## The recipe

Every good curated patch session converges on these steps:

1. **Classify into in-script data** — buckets of `(ref, verbatim evidence)` literals. Human judgment is frozen as data, not prose.
2. **Pull live catalog values** for the `expect:` guards, then assert every ref resolved (fail loud on a typo or drift — never silently skip).
3. **Choose the guard** per row — `ipdb_id` when keyed on the IPDB record, else `year`, else `corporate_entity`.
4. **Emit YAML with `patchkit`** — never `yaml.dump`; never hand-roll escaping.
5. **Keep the audit trail** alongside — the editorial judgment lives in `classify.py` as data (`INCLUDE`/`FLAGGED`/`REJECTED` dicts with a reason on each row), the realized rows + extracted quotes land in `worksheet.csv`, and a short `README.md` narrates the signal, the totals and the dead-end searches (proving a term is absent is what justifies the signal you did use). Prose in the README is the right home for dead-ends — don't build a generator for it.
6. **Validate** on a localhost snapshot, then ship.

## Where the work lives

Authoring artifacts are committed in **pindata**, next to the patches they produce
— not in `/tmp` or `~/.claude/plans`, which lose the audit trail:

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

- **Classification + verbatim source text** comes from **pinexplore** (the DuckDB
  analysis DB: IPDB/OPDB notes, cross-source checks). Output a `worksheet.csv`.
- **`expect:` guards** must come from the **live flipcommons DB** (the serving
  catalog), because guards exist to catch drift against _it_. `gen.py` runs from
  the backend, reads the CSV, looks up live slugs/ids and emits the YAML.

`patchkit` itself is pure Python (no Django, stdlib only) so it imports on either
side; the one Django line — the live lookup — stays in `gen.py`. On the
pinexplore side, `classify.py` can import it too for the source-text helpers
(`sentences`, `sentence_with`, `clean_ipdb_quote`) instead of re-deriving them —
add the authoring dir to `sys.path` first, as `gen.py` does:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # the authoring/ dir
import patchkit as pk
```

## `patchkit` API

Import from the authoring dir (`gen.py` does `sys.path.insert(0, <authoring>)`).

| function                                                                                            | purpose                                                                                                 |
| --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `guard(row, prefer=("ipdb_id","year","corporate_entity"))`                                          | most specific `expect:` dict from a live-values row; `{}` if none                                       |
| `check_resolved(requested, found)`                                                                  | raise if any ref didn't resolve (typo/drift)                                                            |
| `sentences(text)` / `sentence_with(blob, needle)`                                                   | split source free text; pull the sentence containing a needle                                           |
| `clean_ipdb_quote(text, limit=240)`                                                                 | normalize a quote's typography, strip the IPD header and `…: "<passage>` framing, truncate with `[...]` |
| `source_note(source, verbatim, tail="")`                                                            | build `IPDB says "<verbatim>"` (normalizes typography, preserves non-ASCII; mark omissions `[...]`)     |
| `entry(ref, *, create, expect, note, cite, fields, description, tags, retract, commented, comment)` | one correctly-escaped `claims:` block                                                                   |
| `write_patch(path, *, attribution, description, entries)`                                           | a complete patch file                                                                                   |
| `yamlq` / `clean_text`                                                                              | the escaper / the typography normalizer, if you need them directly                                      |

**Escaping is solved — use it.** Notes go through `yamlq` (single-quoted YAML:
literal except `'`, which doubles). This carries both the double quotes in
`... says "x"` and apostrophes, with no backslashes. Do **not** `json.dumps` notes.

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
pk.write_patch("../../0010-game-formats.yaml", attribution="ipdb", description="...", entries=entries)
```

## Schema cheatsheet

Before referencing a field or entity in a patch, confirm it's claimable and learn
its `entity_type` string. From `backend/`:

```bash
# Is the field user-inputtable (claimable), and how is it classified?
# Exempt (system) fields: id, uuid, created_at, updated_at, extra_data. Everything
# else concrete on a ClaimControlledModel is a claim. FK -> value is target public_id;
# M2M -> relationship (namespace: [members]); other -> scalar (value as-is).
uv run python manage.py shell -c "from apps.catalog.models import MachineModel; print([f.name for f in MachineModel._meta.get_fields()])"

# entity_type string for a ref (`<entity_type>.<public_id>`):
uv run python manage.py shell -c "from apps.catalog.models.taxonomy import GameFormat; print(GameFormat.entity_type)"
# taxonomy examples: GameFormat -> 'game-format', ProductionStatus -> 'production-status', Tag -> 'tag'
```

**Vocabulary must be created by a patch, not added to the seed.** Production is
seeded **once** and never re-ingested — it only replays patches. A new taxonomy
value (a `GameFormat`, `ProductionStatus`, `Tag`) added only to the pindata seed
would never reach prod, and an assignment patch referencing it would fail there.
So: create new vocab in an **earlier** patch (its own file, since vocab is usually
`flip-museum` while assignments are source-attributed), then reference it. See
`0009-game-format-vocab.yaml` → `0010-game-formats.yaml`.

## Provenance rules

The attribution, cite-vs-guard and verbatim-ASCII-note rules are canonical in
[DataPatches.md → Authoring a good patch](DataPatches.md#authoring-a-good-patch);
don't restate them here. Two consequences specific to curated patches:

- The carry-a-value-vs-derive-structured-data split usually forces vocab and
  assignments into **separate files** (different attributions). The 0010/0011
  `game_format` patches are the derive case: `flipcommons-catalog` + `cite: ipdb:<id>`.
- `source_note` / `ascii_clean` enforce the verbatim-ASCII note shape for you —
  use them rather than hand-formatting `<Source> says "<quote>"`.

## Validate before shipping

Patches are immutable once applied (per-DB fingerprint), so iterate behind a
snapshot — see [DataPatches.md → Iterating on localhost](DataPatches.md#iterating-on-localhost-snapshot-first)
for the snapshot/rollback loop and naming. The curated-patch wrinkle: apply the
new patches **from an isolated dir** so the already-applied 0001–N are untouched:

```bash
cd backend
mkdir -p /tmp/p && cp ../../pindata/patches/00NN-*.yaml /tmp/p/
cp db.sqlite3 db.pre-00NN.sqlite3                      # snapshot (.sqlite3 -> gitignored)
uv run python manage.py ingest_patches --patches-dir /tmp/p
# verify (see below) ...
cp db.pre-00NN.sqlite3 db.sqlite3                      # roll back
```

**`--dry-run` is misleading for vocab+assignment pairs.** Dry-run doesn't commit
the vocab-creating patch, so the assignment patch reports "FK target does not
exist" for every new vocab value. That's an artifact, not a failure — a real
apply commits the vocab patch first. Validate with the snapshot+apply above, not
dry-run, when one patch creates vocab the next uses.

Verify the result (distribution + provenance) — `citation_instances` carries the
cite, `changeset.note` the note:

```python
from apps.catalog.models import MachineModel
from apps.provenance.models import Claim
from django.contrib.contenttypes.models import ContentType
ct = ContentType.objects.get_for_model(MachineModel)
c = Claim.objects.filter(content_type=ct, object_id=MachineModel.objects.get(slug="hyperball").id,
                         field_name="game_format", is_active=True).first()
print(c.source.slug, c.value, [ci.citation_source.identifier for ci in c.citation_instances.all()])
print(c.changeset.note)
```

Then ship: commit + push pindata, publish to R2, and on prod
`make pull-ingest && make ingest-patches`.

## Gotchas (learned the hard way)

- **Keyword matches catch cross-references.** "Skill Derby" matched `gun game`
  from a sentence about _Bally Derby_. Read the matched sentence; keep an explicit
  override/exclude map for the misses. Re-read every non-trivial assignment.
- **The signal can have false positives.** A note saying "not a pinball" may be
  about a _different_ game it cross-references; the listed game can be a real
  pinball. When unsure, leave the field null — an honest unknown beats a wrong fact.
- **Assert the extracted quote contains the keyword you classified on.** When you
  re-extract a quote by needle (`sentence_with`), a stale or loose needle can land
  on a sentence that never names the mechanism — 0011's `bagatelle` needle
  "came in two sizes" matched a sentence with no "bagatelle" in it. A one-line
  guard (`assert FORMAT_KEYWORD[fmt].search(quote)`) turns that into a loud failure
  at classify time instead of a wrong claim in the patch.
- **Sentence-splitting can sever an inner quotation.** A verbatim sentence with its
  own `"..."` can split at the period _inside_ the inner quote, leaving a dangling
  `"` in the note (`IPDB says "... follows: "Hit the ball.`). It's valid YAML but
  reads oddly. `clean_ipdb_quote` now strips the `…: "<passage>` framing for you
  (returning `Hit the ball.`); only an inner quotation without a colon introducer
  (e.g. `He said "...`) may still need a manual trim.
- **`except A, B:` is valid Python 3** and ruff's preferred style — don't
  parenthesize (a project-wide rule; relevant if your generator catches exceptions).
- **Values are JSON-shaped; YAML coercion is off.** `patchkit._scalar` handles
  this — bare `1996-01-01` would stay a string, `no` stays `"no"`.
