# Data patch description authoring

This is guidance for AI sessions authoring catalog record **descriptions** the encyclopedia-style narrative story that the public actually reads on on a manufacturer, title, model, person or vocabulary page.

## The shape of a description patch

Descriptions are authored in their own patches, separately from all other field types:

- **Attribute the patch to `flipcommons-ai-desc-*`**. Each entity type has its own description actor source named `flipcommons-ai-desc-<entity-type>` — `flipcommons-ai-desc-manufacturer`, `flipcommons-ai-desc-model`, … — NOT `flipcommons-catalog`. People want to know when a description is AI-generated.
- **Include description fields and nothing else.** No other type of field may be attributed to the `flipcommons-ai-desc-*` actors. Include ONLY description fields in a description patch.
- **Number a description patch a few slots ahead.** Researching a description reliably surfaces catalog work the description itself wants applied first — a machine the prose names that needs creating, a record missing the year or classification the wikilink would land on. Those corrections are separate patches (different attribution) and must apply **before** the description that links them, so leave a few empty patch numbers ahead of a description patch for them to slot into; renumbering after the fact works but is churn.

## The shape of a description

A description is a enyclopedia-quality, [fact-checked](#fact-checked), [timeless](#timeless) [narrative](#narrative) supported by [multiple citation sources](#multiple-citation-sources), that [wikilinks everything it references](#wikilinks). It adheres to good-journalism standards: correct attribution, corroboration across [multiple citation sources](#multiple-citation-sources), [no plagiarism](#no-plagiarism), [only report what your can corroborate](#every-statement-supported).

Breaking that down:

### Narrative

It must tell an actual story with a shape — what the thing is, how it came to be that way, what happened to it.

Example: patch [0134's Taito do Brasil](~/dev/flippatch/patches/shipped/0134-taito-do-brasil-manufacturer-description.yaml), a bootleg-house arc, from import shop to factory to liquidation.

Anti-patterns:

- **Don't enumerate the catalog.** Naming a debut or a signature title is good; listing every model is not. The catalog already lists them. A list dates the moment a new item is added.
- **Don't talk about website policy**. Nothing like "This feature is so common that this catalog mostly does not track which machines have it".

### Paragraphs & headings

Use paragraphs. Do NOT write one giant paragraph. One thought per paragraph.

Use section headings like `## Significance` to break up long descriptions, after an untitled lead. Headings are:

- **sentence case** (first word and proper nouns only)
- **factual**: tell the reader what the section covers in terms they already understand ("Origins", "Later use as a trim differentiator"), NOT as a teaser that only makes sense after reading the section ("A moving experience", "Under the glass").

### Timeless

It should continue reading true in 30 years. It shouldn't be falsifiable by subsequent events:

- **Nothing dates**: no "currently", , "as of this writing", "so far". For active manufacturers, write what is true of it in a way that survives its next release: no "their latest machine", "their sole machine".
- **no absence claims**: no "no other source records this": the next source to surface falsifies it.

### Fact-checked

The story must be provably true via citations.

#### Every statement supported

Back each fact with an inline `[[cite:…]]` unless it's a fact already in the catalog. A factual statement resting on existing catalog data needs no citation, but everything else does.

#### Use inline cites

Use inline `[[cite:…]]`, NEVER a single entry-level `cite:`. See [DataPatches.md → Inline citations in descriptions](DataPatches.md#inline-citations-in-descriptions) for the inline `[[cite:…]]` format.

An inline `[[cite:…]]` supports the sentence(s) preceding the marker. The citation marker goes after terminal punctuation, tight against it: `…the dominant maker of pinball in Brazil.[[cite:1]]` — not before the period, not spaced away from it. Partial support of a sentence is acceptable when the uncovered part rides another footnote or existing catalog data. One handle may be referenced from **several** markers; its single quote must then cover every marked sentence.

#### No speculation or puffery

Say what a source says. Not _iconic_, _legendary_, _beloved_, _revolutionary_. Not _likely_, _presumably_, _may have been_ — unless a source hedges and you're reporting the hedge, in which case cite it and say who is unsure.

### Multiple citation sources

Descriptions should cite **at least 4 root sources**, and even more is better. This is partly good journalism (corroborate your sources) and partly to avoid [plagarism](#no-plagiarism).

That's four registrable domains. For example, `bingo.cdyn.com` and `danny.cdyn.com` are registered under `cdyn.com` and they could as one single source.

We have historically not been good about meeting this 4 source MINIMUM, but since our last description campaign, Pinexplore's [web cache system](~/dev/pinexplore/docs/WebCache.md) has gotten MUCH better at fetching and reading docs.

Where corroboration genuinely hasn't surfaced — an obscure machine documented only by one original-research archive — multiple footnotes from that one root beat no description. But it needs user approval.

### No plagiarism

We write in our own words; we do NOT lift the words from another source. The standard is a journalist's: read the sources, establish the facts, then write it yourself.

**Phrase-level lifting.** A sentence that carries over its source's distinctive phrasing or unique turns of expression is plagiarism, whatever the footnote says, and near-copying with a few words swapped (patchwriting) is the same offence more slowly. Shared proper nouns, dates and unavoidable technical terms are not lifting — nobody paraphrases "solid-state" or a company's legal name. Lifted sentence structure and distinctive wording are. The practical test: after you've read the source, look away from it to write the sentence.

**Structural lifting — the single-source spine.** A description whose _selection_ of facts, _order_ and _framing_ track one article is a rewrite of that article even when every sentence is independently worded. This is the failure that footnotes hide best, because each individual citation checks out. Sharing facts with a source is fine; borrowing its shape is not. Independent synthesis is why the two-distinct-roots rule exists — corroboration and original structure are the same discipline seen from two sides.

### Wikilinks

Wikilinks are what make a description part of an encyclopedia rather than a paragraph in a box. **Link every catalog entity the prose names.** A machine, a maker, a person, a place, a theme, a feature, an era — if the catalog holds a record for it and the prose says its name, it gets a marker.

- **Alert user to missing records.** Naming a real title or maker the catalog doesn't hold yet is GOOD — it found a gap! — but leaving it as bare prose is not. Surface missing records to the user.
- **Link fuzzy matches too.** A name the prose spells with different spacing, hyphenation or numbering than the catalog does is still that record, and still gets a marker.
- **Linkable types**: the canonical types are in code, but here's a snapshot: cabinet, corporate-entity, credit-role, display-subtype, display-type, franchise, game-format, gameplay-feature, location, manufacturer, model, person, production-status, reward-type, series, system, tag, technology-generation, technology-subgeneration, theme, title.
- **Don't repeat links**. Only link the first mention.
- **Don't link the record to itself.**
- **Model vs title** Link the `title` when you mean the game as a work (_Medieval Madness_ the design); link the `model` when you mean a specific build (a particular maker's edition, an export edition, an EM/SS pair).
- **Game names are italicised, with the link inside the italics**: `*[[title:attack-from-mars]]*`, `*[[model:cosmic]]*`. When a name needs dating use a parenthetical: `*[[title:medieval-madness]]* (1997, [[manufacturer:williams]])`.

## House writing style

- **No Oxford comma.** "Bally, Williams, Gottlieb, Stern and Zaccaria."
- **Spaced em dashes** — like this — for parenthetical breaks.
- **Straight quotes**, not smart quotes. Straighten `“ ”` on paste.
- **Third person.** Never address the reader, never "we" or "our".
- **Present tense for what a thing is; past for history.** A defunct firm _was_; a cabinet format _is_.
- **Foreign words keep their own characters** — São Paulo, Diversões, Günter. Italicise a foreign term you're glossing, gloss it once in plain English, and keep the gloss out of quotes.
- **Don't name this site, and don't write "the catalog".** The reader can't resolve the referent. Name another site directly when you mean one, and hyperlink the name in the text — a markdown link, not just a footnote: `[eremeka.net](https://www.eremeka.net) dates this to 1974`. A named site with only a `[[cite:…]]` behind it is not linked; the reader shouldn't have to open a footnote to reach a site the prose itself names.
- **No internal jargon**: no _entity_, _node_, _namespace_, _taxonomy_, _record_, _vocabulary_, no code identifiers, no model class names. Write in the trade's own words — the firm, the maker, the machine.

## Guidance for each entity type

### Manufacturer

**Lead** — the name, what the firm was, where, and the span over which it made pinball. _"Taito do Brasil was the Brazilian arm of the Japanese amusement company Taito and, from the mid-1970s until 1985, the dominant maker of pinball and arcade machines in Brazil."_

**Then** — how it started and who ran it → what it built and how it operated, the business model and the technical arc → how it ended, or what it is now, phrased so its next release doesn't falsify it.

**Anchors** — the HQ city as a `[[location:…]]`, the year it started, the year it stopped making pinball.

**Evidence** — a live maker's own site; for a defunct one, company registries, national trade archives, the original-research archives (tilt.it, eremeka, arcade-museum), IPDB's maker notes, and contemporary press.

**Don't** — enumerate the line. Name a debut or a signature title and stop.

Exemplars:

- `~/dev/flippatch/patches/shipped/0134-taito-do-brasil-manufacturer-description.yaml`, the full arc across six paragraphs and seventeen footnotes
- `~/dev/flippatch/patches/shipped/0121-bally-wulff-manufacturer-description.yaml` for a single-record patch.

### Corporate entity

**Lead** — what the name denoted and whose it was.

**Then** — how it relates to the manufacturer brand → the span it covers → the registration or legal facts that pin it down.

**Anchors** — the manufacturer it sits under, the city, the span.

**Evidence** — company registries, trade-name records, the firm's own filings.

**Don't** — retell the manufacturer's story; link to it instead. If everything you can say is already in the manufacturer description, write nothing.

Exemplar:

- `~/dev/flippatch/patches/shipped/0115-italian-corporate-entity-descriptions.yaml` (MM Computer Games): one paragraph, two footnotes, and it stops.

### Title

**Lead** — the name and what it covers: one game, or several builds sharing it.

**Then** — why the models share the name (a re-release, an EM/SS pair, an export edition, a re-theme) → the story around the work itself: its origin, its art, its reception, its place in its maker's line.

**Anchors** — the maker, the year of the first model, and the models it spans when there is more than one.

**Evidence** — IPDB's title notes, the maker's own pages, design and art interviews, contemporary press.

**Don't** — describe gameplay; that belongs on the model. Don't restate the model description one level up.

A title covering a single model with no story of its own is thin by nature — say what the name covers and stop.

Exemplars:

- `~/dev/flippatch/patches/shipped/0132-party-animal-title-description.yaml` for a single title
- `~/dev/flippatch/patches/shipped/0113-italian-title-descriptions.yaml` for the umbrella view over several models

The shape to aim at when a title has a real story of its own is `~/dev/pindata/catalog/titles/blackout.md`, on how Ed Paschke's backglass concept came to be redrawn — seed-era, so uncited, but the narrative is the target.

### Model

**Lead** — the name, what it is, its maker and year, and the person most responsible for it.

**Then** — the theme and what the machine is about → what is distinctive: its rules, its art, its sound, a first → production numbers where a source states them → its relatives: variants, export editions, the game it copies or that copies it.

**Anchors** — maker, year, designer, theme, production run.

**Evidence** — IPDB notes and notable features (scheme-citable and quotable), the maker's own product pages and manuals, design interviews, press.

**Don't** — recite the spec sheet the page already displays beside your prose. The fields carry the specs; the description carries what they don't say.

Exemplar:

- `~/dev/flippatch/patches/shipped/0133-party-animal-model-descriptions.yaml`: three short paragraphs, four footnotes, and a closing sentence on the machine's relatives.

### Person

**Lead** — who they were and their role in the trade.

**Then** — the firms they worked for → the machines they are known for → what became of them or their work.

**Anchors** — the roles they are credited in, the makers, the span.

**Evidence** — interviews and trade press for designers, artists and programmers; for an obscure figure, the archive line that names them plus company registries.

**Don't** — pad four facts into a career profile, and don't list every credit — the page already lists them.

Exemplar:

- `~/dev/flippatch/patches/shipped/0116-italian-person-descriptions.yaml` (Antonio Manili), at the sparse end: four facts, four footnotes, one paragraph. Nothing in the catalog yet shows the documented end.

### Series

**Lead** — what the series is, whose it is, and the span it runs.

**Then** — what the first entry established → what each later entry added or changed → whether it was revived, by whom and how much later.

**Anchors** — the maker, the titles in order with their years, and the designer where one person carried the line.

**Evidence** — the maker's own materials, design interviews, IPDB notes on each entry.

**Don't** — repeat each title's own description. A series is about what connects them.

A series is a curated lineage (Eight Ball → Eight Ball Deluxe), not the IP behind it — that's a franchise.

Exemplar:

- none. The five described today are seed-era one-liners at `~/dev/pindata/catalog/series/` (`eight-ball.md` is 191 characters) and are not the standard. The first series description written to this entry sets it.

### Franchise

**Length** — one sentence.

**Format** — _"Pinball machines based on the Hook film."_

**Exception** — a property whose pinball connection is genuinely obscure — 0059's Battle Dome traces a Japanese toy line into a 1995 coin-op machine, which no reader would reconstruct unaided. That earns a narrative; the Star Wars franchise does not.

Exemplars:

- The gloss standard is the seeded set at `~/dev/pindata/catalog/franchises/` (`hook.md`: _"Pinball machines based on the Hook film."_)
- The exception is `~/dev/flippatch/patches/shipped/0059-franchise-descriptions.yaml` (Battle Dome).

### Game format

**Lead** — what the machine does and how a single play goes.

**Then** — where the format came from, which for the gambling-adjacent formats is usually law or trade economics → its relationship to pinball proper → where it went.

**Anchors** — the era, the makers that defined it, and the legal or commercial force behind it.

**Evidence** — format-specific archives (bingo.cdyn.com for bingos), museum and history writeups, IPDB.

**Don't** — define the format as "not pinball". Say what it is.

Exemplar:

- `~/dev/flippatch/patches/shipped/0174-game-format-descriptions.yaml` (bingo-pinball): three paragraphs, eight footnotes across four root sources, and the law is the spine of the story.

### Gameplay feature

There are multiple registers:

#### A mechanism

(orbits, trap doors, shaker motors, bingo cards).

- **Lead** — define the mechanism in one sentence: what it physically is.
- **Then** — what it does for play → how it differs from the sibling it is most often confused with → the era and makers where it appears, with a named machine or two.
- **Evidence** — mostly definitional. Historically specific mechanism (Magic Squares, Bally Hole, the bingo family) have real sources and carry footnotes.

#### A variant of a mechanism

(2-ball multiball, 6-bank standup targets, left kickback lanes).

- **Lead** — define it against its parent.
- **Then** — only what makes it different: the position, the count, the consequence for play. The parent carries the story.
- **Don't** — pad. Where the shipped corpus padded a variant it reached for unsourced evaluation (_"a balance between chaos and controllability"_).

#### A manufacturer's branded variant

(InvisiGlass, LumaLift, AURA Lighting, Expression Lighting System).

#### instructions

**Don't** anchor on a usage count (_"IPDB catalogs approximately 12 machines with this configuration"_). That is a fact about a source rather than about pinball, and it dates the moment that source adds a machine.

Exemplars:

- `~/dev/flippatch/patches/shipped/0074-gameplay-feature-descriptions.yaml`: `orbits` is the mechanism register, with the sibling contrast (_"Unlike ramps, which lift the ball above the playfield, an orbit stays at playfield level"_) doing the work. Caveat: 0074 predates the inline-cite rules and carries no footnotes, and its universal-feature closers say "this catalog", which the prose rules now reject — copy its shape, not its sourcing or that phrasing.

### System

**Lead** — whose platform it is, the era, and what the hardware actually is.

**Then** — what it drove (displays, sound, lamps) → what it made possible that the previous generation couldn't → which machines ran on it → what replaced it.

**Anchors** — the maker, the year introduced, the processor or platform where a source states it, and the successor.

**Evidence** — the maker's own technical documentation and service manuals, service-community writeups, IPDB.

**Don't** — write "Notable games include X, Y and Z". Name a machine when it illustrates a capability, not as a list.

Exemplar:

- none. All 73 described systems came from the seed (`~/dev/pindata/catalog/systems/`), carry no citations, run about 312 characters, and 15 are built around the "Notable games include" list. A new system description will not resemble these precedents.

### Taxonomy

Tag, cabinet, display type, display subtype, reward type, technology generation and technology subgeneration.

**Lead** — define the class in one sentence a reader with no pinball background can follow.

**Then** — draw its boundary, including what falls just outside it and why → when it appeared and what drove it → what it means for a machine to be in it.

**Evidence** — trade history, museum writeups, maker materials. **These types are not cite-exempt** — the lint exempts only `gameplay-feature`, so a tag or cabinet description footnotes its facts like a manufacturer's does.

**Don't** — stop at a bare definition. Tell the story of the class.

Exemplars:

- the seeded set is the right scope and the wrong sourcing: `~/dev/pindata/catalog/cabinets/cocktail.md` and `~/dev/pindata/catalog/cabinets/countertop.md` are three paragraphs that define the class, draw its boundary and place it in the trade's history, with no citations at all. Match their scope, not their sourcing.
- Not an exemplar: `~/dev/flippatch/patches/shipped/0022-recat-tag-descriptions.yaml`, whose tag descriptions are one-sentence glosses.

### Production status

**Lead** — what qualifies a machine for the status. _"Games that have been announced by the manufacturer but not yet in production."_

**Don't** — narrate. There is no story in a production status, and reaching for one produces invention.

Exemplar:

- `~/dev/flippatch/patches/shipped/0004-production-status.yaml`, which created all five with their glosses. Caveat: it predates the description sources, so its descriptions are attributed `flip-museum` rather than `flipcommons-ai-desc-production-status`; copy the register, not the attribution.

### Theme, location, credit role

No descriptions today, no guidance yet. TBD.
