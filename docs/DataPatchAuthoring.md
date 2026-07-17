# Authoring Data Patches

This doc is the **authoring guidance** for data patches.

For background, [DataPatches.md](DataPatches.md) defines the patch **file format** and how patches are applied.

## Hand-authored or generated?

Hand-authoring is the default; reach for a generator only when a _population_ earns it.

- **Hand-author** native YAML when you can get the whole patch right by reading each entry once — targeted corrections, a record description, a vocab file. Most patches are this, including ones that touch a dozen entities: a description patch has no per-row quote to mechanize, so a script buys nothing. It also stays cheap to revise, since a later change edits the YAML directly.
- **Generate with [DataPatchKit.md](DataPatchKit.md)** when you're classifying a population from source data — many rows, each needing a verbatim quote extracted and escaped from source free text. The trigger is the repeated mechanical per-row work, not the row count: a generator can make each classification field a _required_ per-row key, so a row that omits it fails loudly instead of silently inheriting a wrong value — a model defaulting to `game_format: pinball` is how a non-pinball machine slips through. Enforced uniform coverage is the point. Keep a worksheet recording every search behind the rows — the dead ends too, since proving a term is _absent_ from the sources is what justifies the signal you did use — so the editorial judgment stays auditable. The cost lands later: edits go through the generator, never the YAML, so don't generate a patch you expect to keep hand-tweaking.

Decide per patch, not per patch set: a generated bulk patch and hand-written one-offs can sit side by side.

## Schema cheatsheet

Before referencing a field or entity in a patch, confirm it's claimable and learn its `entity_type` string. From `backend/`:

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

## Authoring a good patch

These principles apply whether you hand-author or generate.

### Attribution of the overall patch

**Attribute the overall patch to the `flipcommons-catalog` source by default.** It's Flipcommons' own attribution for values we research, scrape and classify ourselves, and it owns the overwhelming majority of patches. Anything web-scraped where we apply editorial judgment is `flipcommons-catalog`; scraping a fact off IPDB or Kineticist does **not** mean attributing the patch to them. Deriving a structured value by classifying a source's free text (parsing IPDB notes into a `game_format`, say) is this same default case, not an exception: `flipcommons-catalog`, with `cite:` to the source text as evidence, its `quote:` carrying the excerpt you classified — there's no source claim to supersede, because the source never had that field.

Reach for a different attribution only in these cases:

- **Retracting or superseding another source's existing claim** → attribute to _that_ source (`ipdb`, `opdb`, …), so you act on its own claim. This is the only time `ipdb`/`opdb` attribute a patch — never a fresh first-party assertion.
- **Wholesale import of structured data from an external site or API** → create or reuse a source for that site and attribute to it: the site supplies the field directly, so there's no judgment of ours to own.
- **A first-party curatorial source states the fact directly** → that source — `flip-museum` for museum-curated facts no one else claims.
- **AI-generated record descriptions** → the per-entity-type description source `flipcommons-ai-desc-<entity-type>` (see [Record descriptions](#record-descriptions)).

### One record per entry

**Each entry targets exactly one record.** By default keep that record's fields together in the one entry under a single `note`/`cite`. When the fields have **distinct evidence**, split them instead — each piece of evidence its own `ChangeSet` with its own `note`/`cite`, either as separate entries on the same record or as `changesets:` items under one entry, as long as the fields are disjoint (see [DataPatches.md](DataPatches.md#notes--citations)).

### One quote supports one fact

**Each quote should support exactly one fact, so it can be checked — or challenged — on its own.** Fields share a changeset only when they share the evidence: a catalog row stating year, name and maker in one line is a single fact cluster; a machine's format tag two lines below it is a separate fact and gets its own `changesets:` item with its own cite and quote. The `[...]` join is for one statement whose text spans several passages — never for gluing unrelated sentences together so one quote can blanket-cover an entry's fields.

Three boundaries:

- **A fact with no quotable evidence rides the header.** An inference the patch is allowed to make (a 1960s machine's `technology_generation`, a theme read off the name) has no span of its own; it stays on the entry header rather than getting an evidence-free item.
- **A reassertion that changes nothing can't carry its own changeset.** The apply engine rejects a provenance-carrying unit whose value already matches the record ("changes nothing"), so a field you're re-stating purely to add evidence must ride a unit that changes something — or be dropped.
- **A maker description citing a machine catalog may aggregate rows.** Several of the maker's machine rows joined with `[...]` are collectively the page's one statement about that maker's activity and years — a sanctioned reading of "one statement", not unrelated facts glued together. Keep it to the minimum rows that support the claimed span.

### Quote the evidence on the cite

**Put the verbatim source excerpt in `quote:` on the `cite:` mapping** — see the mapping form in [DataPatches.md](DataPatches.md#notes--citations). An inline `cites:` entry takes the same mapping form, so a footnoted description's excerpts ride the footnotes themselves; everything below applies to both carriers. Quote the source _verbatim_ and mark your own omissions with `[...]` — that's a literal square-bracket pair around three ASCII periods, not the `…` character; when a statement spans several passages, join the spans with `[...]` in source order. **Preserve the source's own characters**, including non-ASCII letters in foreign-language quotes (e.g. `Günter`, `gegründet`) — quotes are stored as UTF-8, so don't strip or transliterate them. **Quotes stay in the source's own language**: never translate a quote and don't add any language designation — display-side translation is the reader's tooling's job, and a translation or gloss you want to record is interpretation, which belongs in the `note:`. Only normalize stray _typography_ that's a copy-paste artifact rather than part of the quote: straighten smart quotes (`“ ”` → `"`) and spell out an ellipsis `…` as `[...]`. **The source's own typos stay verbatim** — "commerical", a misspelled name, a non-breaking hyphen — the verifier requires the exact text and ctrl-F honesty demands it. A reviewer should be able to follow the citation and ctrl-F find each span.

**Reuse before re-derive.** When a footnote states the same fact as an already-verified quote for the same entity and source elsewhere in the patches, reuse that quote verbatim (or widen it) rather than minting a divergent transcription of the same evidence.

### Note only when there's something to explain

**`note:` is the edit summary — rationale beyond the evidence.** Uncertainty, cleanup comments, merge explanations, disambiguations and paraphrased source facts ("what the source states, in my words, and why the value follows") belong here; a verbatim excerpt does NOT — that's the `quote:`. A cite with a quote usually needs no note at all. Do not write the legacy `<source> says "<quote>"` scaffolding: the citation already names the source and the quote carries the evidence.

### Cite most entries

**Cite external evidence with `cite:` on every substantive claim.** Skip the cite only when the evidence _is_ the entity's own data — then state it in the `note:` instead ("Its name contains the word 'prototype'"). The other exemptions are scaffolding entries (below) and aliases/abbreviations (see [Aliases and abbreviations](#aliases-and-abbreviations)).

**Pick the cite ref form by source:** `scheme:identifier` for IPDB/OPDB records, or a raw `http(s)://` URL for any other web page (a forum thread, an archive scan, a manufacturer's page). Reach for the scheme form whenever one exists; the URL form is the escape hatch for sources without a scheme. A URL cite needs its **website root seeded first** — see [Citation sources](#citation-sources).

**The cite can target a different record than the claim.** When the evidence lives in a _different_ record's note (a cross-reference — "‹other game› is not a pinball"), `cite:` the record that contains the statement.

**Only assert what a source supports.** If you can't point to evidence, leave the field unset rather than guess: an unset value reads as "unknown", a wrong claim reads as fact.

Target-creating entries can be **scaffolding** — obvious records like Titles before Models or Locations before corporate-entity claims — and may omit per-entry `note:`/`cite:` when the patch `description:` says why they're needed. The substantive assignment that uses them still needs normal evidence.

### Scheme cites: where the quotable text lives

**A scheme cite's `quote:` verifies against a fixed evidence corpus, not an ad-hoc fetch** (flippatch's `make verify-quotes` checks every quote against it):

- **`ipdb:<id>`** — the `ipdb_machines` table in pinexplore's `explore.duckdb`. The quotable text mirrors what the IPDB page renders: the title as a bare heading, then `Manufacturer:` / `Type:` / `Players:` / `Theme:` label-value rows, then the Notable Features and Notes prose — so a structured-field quote like `Type: Electro-mechanical (EM) [...] Players: 1` is legitimate and stays ctrl-F honest on the page. Cite the machine page whose record carries the field; IPDB has no maker pages, so a maker-level fact (a location, say) cites one of that maker's machine pages.
- **`opdb:<id>`** — the cached `https://opdb.org/machines/<id>` page in pinexplore's web cache. OPDB renders only label-value fields, so quotes read as terse spans (`Cactus Canyon Continued [...] Manufacturer - Eric Priepke [...] Converted game`); a fact implied by OPDB's group structure (the donor title of a conversion) is never stated as text and stays partially supported.
- **`youtube:<id>`** — the cached canonical watch URL, whose page text is the video's caption-track transcript. See [Video citations](#video-citations).

### Video citations

**Fetch the video into the web cache like any URL.** Pinexplore's `web_fetch.py` routes any YouTube URL shape (`watch?v=`, `youtu.be/`, `/shorts/`, `/live/`) through yt-dlp and caches the best caption track — manual subtitles over auto-captions, the original spoken language over machine translations — with the spoken-line transcript as the page text. Then:

- **Quote the transcript** like any web quote; `verify-quotes` resolves `youtube:<id>` to the cached watch URL.
- **Add a timestamp `locator:`** to point at the moment; the stored `.vtt` blob keeps the cue timing for finding it.
- **Auto-captions are ASR text.** Verbatim means verbatim ASR — a misheard name stays as the transcript has it, like any source typo. A machine-translated caption track is not evidence; quote the original language.
- **A captionless video can't carry a quote.** Livestream archives often have no caption track at all; the fetcher warns loudly and caches nothing. Cite the written record the video's description usually links (an awards show's results page, a maker's announcement post) for the fact itself, and keep the video footnote — quote-less — as provenance for the event.

### Prefer primary sources

**Cite primary sources over secondary ones.** A maker's own site, a period magazine scan, a government registry, an interview in the subject's own words, an original-research catalog hosting its own artifacts — these beat any site that compiles facts from elsewhere. Encyclopedias, databases and aggregators are **secondary**: Wikipedia, weblio, IPDB, OPDB, Kineticist, Pinside, company-registry aggregators (b2bhint, bisprofiles) and the like.

Before quoting a secondary source, do both of these:

1. **Web-search for the same fact from a primary source** and cite that instead.
2. **Follow the secondary source's own citations** (a Wikipedia article's references, an IPDB note naming the magazine it read) to the primary material and cite that instead.

Prioritize, don't forbid: when the primary is unreachable — a script-rendered page the cache can't capture, an unlinkable registry, trade press that would take issue-by-issue reading to locate — cite the secondary with a quote and say in the `note:` what the true primary is, so a later pass can upgrade the cite.

## Patch description

Every patch should contain a top-level description. It maps to the `IngestRun` note — visible only in Django admin (and git), where it reads like a commit-message title, not a place for detail. Keep it to **a single short sentence (the flippatch lint caps it at 80 characters)**: a general summary of what the patch does, not a per-changeset rundown. Stay general enough that it survives adding another change before the patch is finalized — don't restate the details of each changeset, and don't reference other patches by number (that cross-patch bookkeeping goes stale and belongs nowhere public; per-change reasoning belongs in `note:` fields). Examples:

- ❌ NO: Models for the new active makers, one per game. Each model's title (0053) and corporate entity (0051) already exist. Production status reflects each game's real state: Alice Goes to Wonderland is shipping (produced); the rest are announced (a pre-order, an intended launch, a trademark filing). Corporate inception years stay off the entities; these model years carry the makers' timeline. The Wonderland and Pawlowski home machines carry the home-use tag; the already-catalogued Ramp's Road Trip is tagged widebody.
- ✅ YES: Models for the new active makers created in a previous patch.

## Citation sources

A `cite:` to a web URL needs its **website root** — declared via a top-level `sources:` block (mechanics and the get-or-create policy are in [DataPatches.md → Citation sources](DataPatches.md#citation-sources)). The `sources:` block is processed before claims, so a root declared in the **same** patch is citable in that patch (order-independent), or it can come from an earlier patch.

Write a root's `description:` to only describe **the source itself** — what it is; do NOT include why this patch cites it:

- ❌ NO: `Company-registration aggregator; used for the registered address of Wonderland Amusements LLC`
- ✅ YES: `Company-registration aggregator`

This is because a root is reusable, so a reason-specific description goes stale the moment the next patch cites the same root for an unrelated fact. Leave per-fact reasoning to the citing entry's `note:`.

## Record descriptions

Some patches set narrative record descriptions (Manufacturer, Model, …) — prose, not classified values. The rules:

- **No speculation.** Keep it factual; tell the story, don't guess.
- **Every statement supported.** Back each claim with an inline `[[cite:…]]` footnote or a fact already in the catalog. A statement resting on existing catalog data needs no citation; anything else does — and every description must footnote **at least one** fact (a description with no inline citation at all is rejected by the lint, so a purely-catalog description still cites its primary source).
- **Attribute to the description source.** Each entity type has its own description source named `flipcommons-ai-desc-<entity-type>` — `flipcommons-ai-desc-manufacturer`, `flipcommons-ai-desc-model`, … — not the generic `flipcommons-catalog`. These sources already exist in the database, so just reference one — unlike a `cite:` website root, you don't create it in an earlier patch.
- **Cite each fact inline.** A narrative description backs individual sentences with **inline `[[cite:…]]` footnotes**, never a single entry-level `cite:` covering the whole field — see [DataPatches.md → Inline citations in descriptions](DataPatches.md#inline-citations-in-descriptions) for the format (numeric handles plus a `cites:` map for new citations; durable slugs for existing ones). The editorial lint enforces two rules here: a `description:` unit must carry **at least one** inline `[[cite:N]]` footnote (`description-needs-inline-cite`), and it may **not** carry an entry-level `cite:` (`description-no-entry-cite`). Even when one source covers the whole description, footnote it inline (a single `[[cite:1]]` at the end is fine) so each statement is individually verifiable. Inline `cites:` count as provenance, so all of an entity's cited fields belong in **one changeset**. (Patches already applied to production predate these rules and are grandfathered; supersede them in a new patch under the same `flipcommons-ai-desc-<type>` source if you need to convert them.)
- **A footnote's quote is a point citation: it supports the sentence(s) its marker punctuates.** An inline `cites:` entry takes the same `{ ref, locator, quote }` mapping form as an entry-level cite, and its quote covers the facts of the marked sentence — not the whole description; a fact in another sentence belongs to its own marker. Partial support of a sentence is acceptable when the uncovered part rides another footnote or existing catalog data, but flag it for review. One handle may be referenced from **several** markers; its single quote must then cover every marked sentence, spans joined with `[...]` in source order.

### Rehydrating a description for re-edit

To reword one sentence of an existing cited description without re-supplying every other citation, **dump the current text back to authoring form** and edit that:

```bash
cd backend
uv run python manage.py dump_patch_entry model.mazatron > /tmp/p/0NNN-reword.yaml
```

The command emits a complete, runnable patch document with the entity's markdown fields in authoring format (`[[cite:<slug>]]`, real durable slugs in place) — edit a sentence, drop the marker for any citation you remove, and resubmit. Existing slugs self-resolve, so an untouched citation re-applies to byte-identical storage and diffs as a no-op (no churn, no orphaned instance); only a sentence you actually change writes.

One behavior to know:

- **`attribution:` defaults to the field's _owning_ source** (the `flipcommons-ai-desc-<type>` that holds the winning description claim), because a re-apply is a faithful no-op only under that source — `_diff_claims` compares within a source. `--attribution <slug>` overrides it, which **forks** the text into a new source-owned claim rather than preserving no-op semantics. A description that was last edited **interactively in-app** is user-owned (no source) and dumps only with an explicit `--attribution`.

### Manufacturer descriptions

- **Don't just list titles.** Naming a debut or signature title is fine; enumerating the catalog is not.
- **Avoid phrasing that dates.** For an ongoing (non-defunct) concern, skip "their latest model", "their one machine" and the like.
- **Give the anchoring facts from the data** — the HQ city, the year founded and (if defunct) the year it stopped making pinball.

## Creating new catalog entities

Creating records (rather than correcting seeded ones) has its own discipline. Precedents: the early-Japanese sweep (0043–0046 + 0049), the active-makers sweep (0050–0054), and the CEFF pilot (0081) from the tilt.it Italian sweep.

### Creation order and patch layout

Dependencies point one way: **Manufacturer → CorporateEntity → Title → Model**. A FK target must exist in the seed, an earlier patch, or an **earlier entry in the same patch** — forward references within a patch are unsupported, and a Location parent must exist in an _earlier patch_ (same-patch location parents don't resolve). Citation website roots must be seeded in the same or an earlier patch before any URL cite against them.

**Prefer the vertical per-manufacturer layout** (0081): one maker's manufacturer → corporate entity → title(s) → model(s) in a single dependency-ordered patch. All the related data reviews as one unit, and a generated sweep emits one such patch per maker. The depth-split series (0043–0046: all manufacturers, then all corporate entities, then titles, then models) predates same-patch dependency support and survives as precedent, not as a layout to copy — reach for a split only where the dependency genuinely spans patches (location parents; citation roots shared by many makers).

### Fill every field you can — grounded in DomainModel.md

A new record should carry every field the evidence supports, and no field it doesn't. [DomainModel.md](DomainModel.md) is the authority on what fields exist and what their values may be. Per-type checklists:

- **Manufacturer** — `name` (the brand as it appeared on the cabinet), `manufacturer_alias` for spelling/legal variants, `operating_status` when a source states it (leave unknown rather than guess — the 0049 Kato precedent).
- **CorporateEntity** — `name` (the legal/corporate incarnation, distinct from the brand), `manufacturer`, city-level `location` (see [Corporate Entity locations](#corporate-entity-locations)), active years when stated, `corporate_entity_alias` for native-script or variant names.
- **Title** — a thin identity shell: `name`, `abbreviation` where established; `franchise`/`series` only with evidence. Credits, themes and hardware live on the Model.
- **Model** — `name`, `year`, `title`, `corporate_entity`, `technology_generation`, `game_format`, player count, `production_status`, display and system where known, `ipdb_id`/`opdb_id` when the machine is cross-listed, `theme` and credits when a source states them.

Required minimums for a `create: true`: every entity needs `name` plus a cite; a Model additionally needs `title` and `corporate_entity`. Everything else is fill-what-the-evidence-supports — a Model with no known year is acceptable (say so in the `note:`), a Model with an invented year is not.

**A Model's `year` (and `month`) is the manufacture date — not the trade-show presentation, not the announcement.** A source dating a different event ("presentato Enada ottobre 1974", a reveal, a flyer date) is not `year` evidence: leave the field to a source that dates manufacture, and keep the presentation/announcement date in the `note:` (with its quote) or the description. When two sources disagree on a year, check first whether they are dating different events before treating it as a conflict.

### Uncertain values

Assert the best value and record the uncertainty in the `note:` — the model has no "approximate" flag (0042 precedent: eremeka's `~1967` becomes `year: 1967` with the `~` quoted in evidence). A source's `(?)` marker, a year range, or a disputed spelling all follow the same rule: pick the best-supported value, keep the hedge visible in the note and quote. Never invent precision the source doesn't have.

### Uncertain existence

A value can be hedged; a record cannot. When the source itself is unsure a machine _exists as a distinct product_ — tilt.it's CEFF page says outright it is unclear whether "Joker Ball" names a second model or a gameplay feature of Five Martians — do **not** create the record. Keep the ambiguity in the created sibling's note or description (cited), record the decision in the authoring dir's README, and revisit if evidence surfaces. The same applies to version variants: two cosmetic/scoring versions reported in passing stay one Model with the variance noted, unless a source distinguishes them as separate products (then see variants below).

### Single-source facts

Corroborate wherever possible — IPDB first (scheme-citable, quotable), then targeted web research — but a fact citable from only one original-research archive (eremeka, tilt.it) is still assertable: these archives are effectively primary for obscure machines. When corroboration was sought and not found, say so in the `note:` on the create — and phrase it as the **authoring act, not a claim about the world**: "corroborating sources were sought at authoring time and none found" stays true forever, while "no other source documents the firm" is falsified by the first new website that mentions it. The same durability rule applies to any note: never write a present-tense absence or uniqueness claim ("the only known…", "documented nowhere else") when a past-tense search statement carries the same information. Descriptions still aim for two distinct root sources; where corroboration hasn't surfaced, multiple footnotes from the one root beat no description.

### Titles for one-off machines

Every Model gets a Title, even a one-off from a maker with one machine. Disambiguate colliding title slugs with a maker or era suffix (`home-run-nihon-tenbo`), keeping the display `name` clean.

### Re-releases, kits and conversions across makers

When a machine is another maker's game re-released, rebadged, kitted or converted, first classify the relationship per [DomainModel.md](DomainModel.md): remakes share the original's Title; `variant_of` links cosmetic variants; copies, complete conversions and conversion kits use `model_relationship` edges as described below. A source listing electromechanical and solid-state versions of a game, or 1P/2P/4P editions, describes **separate Models**, not `variant_of` variants: reserve `variant_of` for cosmetic or packaging variants of one product. Cite the source line that states the relationship, and when sources disagree, prefer the better-evidenced attribution and document the disagreement in the `note:`.

## Corporate Entity locations

Corporate entity locations should be a city. Not a country, not a state, not a region. Even if it's hard to find the city, find it. If you can't find a conclusive citation, don't include a citation. We'd rather have an uncited city than no city at all.

## Aliases and abbreviations

Aliases (`manufacturer_alias` and the other `<entity>_alias` namespaces) and `abbreviation` (Title + Model) are relationship members carrying a **bare string**, not a public_id. Author them with the literal registered namespace as the field key and a list of strings:

```yaml
claims:
  - manufacturer.stern:
      manufacturer_alias: [Stern Pinball, Stern Inc, Stern Electronics]
```

- **Case.** Alias values **case-fold** for identity — `Stern` and `stern` are the same alias — but the original case you write is preserved as the display form. Abbreviations are stored **verbatim** (`MM` ≠ `mm`), so write them exactly as they should render.
- **No duplicates within one list.** Two members that fold to the same identity (`[Stern, stern]`, `[MM, MM]`) are rejected — list each distinct value once.
- **Length.** Members are length-checked at build time against the model's column bound (alias 200, abbreviation 50); an over-long member is rejected on `--dry-run`, not silently truncated.
- **Remove** drops a member exactly like an FK member: `remove: { manufacturer_alias: [Stern Inc] }`, attributed to the source holding the membership claim.
- **No `note:` or `cite:` needed.** Aliases and abbreviations don't require `note:`/`cite:`. It fine for them to ride in a Change Set whose `note:`/`cite:` supports other things.

## Credits

A credit attaches a `{person, role}` pair to a model or series. Each member is a **single-key mapping** under `credit:` — the key is the person public_id, the value is the role (a `credit-role`) public_id (see [DataPatches.md → Credits](DataPatches.md#credits) for the full syntax). Authoring guidance:

```yaml
claims:
  - model.medieval-madness:
      cite: ipdb:4032
      credit:
        - brian-eddy: design
        - dan-forden: software
        - dan-forden: sound # one person, two roles → two credits
```

- **Cite the credit.** Unlike aliases, credits are substantive facts and should carry evidence. An entry-level `cite:` attaches to every credit in the entry; if different credits come from different sources, split them across `changesets:` items, each with its own `cite:`. The pinball cataloguing standard is IPDB's credit block — cite it (`ipdb:NNNN`); credits are a deliberate exception to [Prefer primary sources](#prefer-primary-sources), since IPDB's credit blocks are the field's accepted reference.
- **Person and role must resolve.** Both are public_ids that must already exist — in the seed, an earlier patch, or earlier in this same patch. A new `credit-role` is creatable with `create: true` (like `tag`/`theme`); create unfamiliar people the same way before crediting them.
- **One person, many roles.** Repeat the person across list items — `dan-forden: software` and `dan-forden: sound` are two distinct credits, not a duplicate. The duplicate guard only rejects the _same_ `{person, role}` pair twice in one entry.
- **Series vs model.** Put a credit on the `series.*` entry only when it genuinely applies to the series as a whole (e.g. an original designer credited across the line); a credit specific to one machine belongs on its `model.*` entry.
- **Remove** drops a credit like any other member: `remove: { credit: [{ john-youssi: art }] }` (or the block form), attributed to the source holding the claim.

## Model relationships

A model relationship types an edge from a model to the machine it copies, rethemes, converts or fits as a kit (see [DataPatches.md → Model relationships](DataPatches.md#model-relationships) for the full syntax). Each member is an explicit-key mapping with one target key (`target_machine` public_id XOR `target_label` plain text) plus `relationship_type` and `license_status`. Authoring guidance:

```yaml
claims:
  - model.al-capone:
      cite:
        - ref: ipdb:5176
          quote: "This game is a copy of Bally's 1982 'Speakeasy'."
        - ref: https://augustocampos.net/taito-brasil
          quote: "certamente não era a única empresa a usar a Reserva de Mercado como escudo para copiar impunemente a tecnologia e a jogabilidade dos pinballs do exterior: a LTD, sediada em Campinas, fazia o mesmo"
      model_relationship:
        - target_machine: speakeasy-2
          relationship_type: copy
          license_status: unlicensed
```

- **Source the two axes separately.** The target and the licensing status are different facts, often established by different sources. Citations attach to the edge as a set; each citation's quote should make clear which fact it supports.
- **`license_status: unknown` is the honest default** — write it whenever no source establishes authorization either way. Do NOT infer `unlicensed` from a source merely calling something a "bootleg region" copy; `unlicensed` needs its own evidence.
- **Use `target_label` only when the machine isn't seeded or the target is plural** ("several Gottlieb EM models"). Write the label as it should display after "Conversion kit for …" / "Copy of …"; it renders as plain text with no links.
- **One label target per model.** Fold all unresolved targets into one display string ("Hi-Score or Super Score"). A later assert rewords that edge in place; `remove:` by `target_label` removes the slot regardless of its current wording.
- **Bootlegs, licensed builds, rethemes and kits are edges.** These common terms map to edge values, not to tags or fields of their own: a bootleg is `(copy, unlicensed)`, a licensed build is `(copy, licensed)` and a kit is `conversion_kit` (own-manufacturer conversions are `licensed`, look for evidence as to whether other-manufacturer conversions are unlicensed, default to unknown).
- **Distinct from `variant_of`/`remake_of`.** Cosmetic variants and official remakes stay scalar FK fields on the model; the edge table is for copies, conversions and kits only.

## Validation process

How to validate your changes:

1. [`--dry-run`](#dry-run) is the cheap first pass: it parses the patch and runs every structural check without writing.
2. [Validate via snapshot](#validate-via-snapshot) is the real check: it commits to localhost, so you see the resolved effect in the running app and can validate cross-file dependencies, then roll back.
3. [Hand off to user](#hand-off-to-user) only after those. Committing and `make push` are the user's call.

### Dry run

`--dry-run` parses the patch and runs every structural check (schema, escaping, citation roots) without writing. This catches most single-file mistakes in seconds. However, what it cannot do is show the resolved result or validate a dependency that spans patch files, because it commits nothing.

**`--dry-run` can't validate a reference to an entity from another patch file.** Dry-run commits nothing, so if a later patch references something an earlier patch file creates — a title before its model, a manufacturer, a parent location, a vocab value — the later patch reports "FK target does not exist" for it. When you are testing multiple patch files together where one depends on a previous, validate with the snapshot+apply above instead of dry-run.

### Validate via snapshot

Because a patch is immutable once applied (see [DataPatches.md → The ledger](DataPatches.md#the-ledger-applied-once-immutably)), you can't tweak it and re-run against a DB that already has it. Instead, iterate behind a DB snapshot: copy the SQLite file before applying and restore it to roll back. Name the snapshot after the patch (`db.pre-NNNN.sqlite3`) so it's clear which state it captures; the `.sqlite3` suffix keeps it under the gitignored `*.sqlite3` rule. Apply your new, uncommitted patches **from an isolated dir** so the already-applied 0001–N stay untouched:

```bash
cd backend
mkdir -p /tmp/p && cp ../../flippatch/patches/00NN-*.yaml /tmp/p/
cp db.sqlite3 db.pre-00NN.sqlite3                      # snapshot (.sqlite3 -> gitignored)
uv run python manage.py ingest_patches --patches-dir /tmp/p
# verify in the running app / Django admin ...
cp db.pre-00NN.sqlite3 db.sqlite3                      # roll back
```

#### Verify snapshot

After applying, spot-check that the change resolved the way you intended — pull a representative entity and confirm its winning claim carries the right source, value, `cite:` and `note:` (`citation_instances` carries the cite, `changeset.note` the note):

```python
from apps.catalog.models import MachineModel
from apps.provenance.models import Claim
from django.contrib.contenttypes.models import ContentType

ct = ContentType.objects.get_for_model(MachineModel)
c = Claim.objects.filter(
    content_type=ct,
    object_id=MachineModel.objects.get(slug="hyperball").id,
    field_name="game_format",
    is_active=True,
).first()
print(c.source.slug, c.value, [ci.citation_source.identifier for ci in c.citation_instances.all()])
print(c.changeset.note)
```

### Hand off to user

Committing and `make push` in flippatch are the user's call — never automatic, never something you do yourself. `make push` (publish to R2, whence other environments pull via `make pull-patches && make ingest-patches`) is a deliberate user command on the same footing as `git commit`/`git push`; the authoring loop ends at localhost validation and never touches R2.
