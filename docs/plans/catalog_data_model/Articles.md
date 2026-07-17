# Articles

This doc proposes a feature whereby contributors could author editorial articles about pinball.

> This doc is in **⚠️ IDEATION PHASE**. It's not ready for implementation.

## What the feature is

An **Article** would be a new entity, that lives at its own slug (e.g. `/articles/italian-bootlegs` or `/pages/italian-bootlegs`), wikilinkable (`[[pages:italian-bootlegs]]`), and built from the same claims/citations/wikilink machinery as every other claims-controlled entity.

### One type of editorial page

In order to keep things simple for contributors, and to simplify the system itself, we will only ever have ONE type of editorial page. We will never build separate types of pages for "filter pages" and "concept pages" and "essays" and "list pages" that are separate entities. One entity, one authoring surface, one mental model.

That means this feature needs to be flexible enough to support lots of different types of editorial content, including but not limited to:

- a two-sentence concept gloss: `bootleg`
- a computed-set curation: `italian-bootlegs`
- a long historical essay: the story of Spanish EM manufacturers
- a Wikipedia style page
- a Kinteticist style article, maybe an interview

### Example Articles

Examples of specific Articles we might want to write:

- `italian-bootlegs`: an Article on unlicensed copies in Italy
- `bootleg`: explains the unlicensed copy ("bootleg") concept in general, talks about the history of bootlegs, links to more specific bootleg pages like Italian bootlegs
- `copy`: an Article that defines what a copy is, and talks about licensed vs unlicensed (bootlegs), and links to those articles
- `conversion`: an Article on machines that are conversions
- `conversion-kit`: an Article that defines what a conversion kit is, and talks about specific conversion kits
- `remake`: an Article that defines what a remake is, and talks about specific remakes (Medieval Madness is the banner remake)
- `variant`: an Article that defines what a variant is, and lists all the variants. Would be cool to have a dynamic list that lists all the variants of a specific model, like Godzilla.
- `chicago` or `chicago-manufacturers`: an Article on how Chicago is and has always been the center of the pinball universe. This is an article we really want to write. It might conflict with an existing URL, `location/usa/il/chicago`, and thus needs careful design.

### Relationship with other markdown-enabled entities

An Article is not the only way to write editorial content; every catalog record can have editorial content, because every catalog entity is Describable and thus has a markdown description. Article is for editorial content that crosses multiple catalog records.

### This is not a domain-specific entity

The Article concept is not specific to the pinball domain. The Article data model should not live in the Catalog Django app; it should not change at all when we apply this system to a new domain like baseball.

- I'm not sure where it _does_ live; maybe in its own app?
- I'm not sure whether `Article` would extend the `Catalog` abstract base class or instead be composed of some of the same primitives of which `Catalog` is composed.

## Principles

### Build like a platform

When possible, make a capability a generic part of a lower-level system, rather than specific to Article. Examples:

- Add support for lists to Markdown in general, and not just Article markdown.

### Semantic authoring, derived presentation

Several capabilities below, such as lists and images and accordions, discuss how to control the UI. Philosophically here's our position:

- **Default to simplicity**. This is a tool for volunteers. Don't make them learn a bunch of sophisticated UX. More UI control = more complexity = bad.
- **Content must be semantic**. The content should be around in 100 years, but UIs change. We have a sidebar now, but might not in a year. Don't give contributors presentation options that bind the content to a specific UI. Stick to semantic content -- like at most, mark a piece of content as 'secondary'. But even there, prefer automatic rules where the contributor has zero presentation choices to make.

## Open questions

### Naming

Do we call this `Article`? `Page`? `Story`? Something else?

## Product design

### Authorization

No special authorization logic to author Articles. This gets exactly the same authorization model as the rest of the catalog data, meaning:

- Any contributor can edit any Article
- You must be logged in, no anonymous edits

### Inline citations

An Article's markdown content must support inline citations, same as every other markdown content in the system.

The markdown body is the same content type as a catalog description, so inline citations (`Markdown.svelte` + the citation tooltip/reference machinery) work for free.

This is non-negotiable, and it's already met by reusing the description pipeline.

### Citability

Do we allow claims on other types of records to cite Articles?

Epistemically, most Articles will be project-internal synthesis, not a primary source. However, we also want to support original content, like interviews with pinball makers, though we do not yet have any of that.

If we do allow it, how do we keep it from laundering unsourced claims?

How does prior art handle this? Does Wikipedia allow citing other Wikipedia pages?

### Lists

An Article can present lists of entities.

#### Dynamic lists

[ModelRelationships.md](ModelRelationships.md) has use cases for Article. We initially considered modeling its relationships as catalog entities so that they'd automatically get markdown description pages and wikilinks, but finally decided to instead use Articles for this. Its examples are all about rellationships — copies, conversions, rethemes. Curators want to gather those relationships into a list. Real lists we'd want to build from that material:

- **Italian bootlegs** — every unlicensed copy made in Italy (the RMG machines and their kind).
- **Bootlegs everywhere** — every unlicensed copy, full stop: Spain (Petaco, Maresa), Italy (RMG), Brazil (LTD do Brasil), all in one place.
- **Licensed copies** — the opposite: machines built _with_ permission, like VIFICO's run under license from Gottlieb.
- **Conversion kits** — every kit that turns one machine into another (Geiger, Good Year, Sky Warrior).
- **Conversions** — every machine actually built out of a donor machine (the j-martina games).
- **Rethemes** — every machine that reskins another one's gameplay with new art (Metallica reskins, Shrek).
- **All the variants of one game** — e.g. every variant of Godzilla, on the Godzilla-related Article.
- **One maker's whole output** — every machine RMG ever built.

These lists are dynamic; as new machines get catalogued, "Italian bootlegs" pick them up without re-editing the Article.

I imagine this would be some sort of stored filter over the real listing-filter vocabulary; `location=italy + relationship-type=copy + license-status=unlicensed` → "Italian bootlegs". The stored filter must validate against the actual listing-filter vocabulary. That vocabulary must express both scalar-FK relations (`variant_of is set`) and edge type/status predicates.

Ordering: we should probably start by using the system's default sorting for the entity. Otherwise the curator would have to specify a sort key from the listing vocabulary (by name, by year, by manufacturer). Let's not go there in v1.

#### Static lists

An explicit manually authored, manually ordered set of specific entities: these five models, these three people, this manufacturer.

I suspect these lists are homogenous, each list containing a single entity type. This allows for eventually building some sort of nice picker UI.

These probably do not need to be built for v1.

#### List rendering

Some options:

- **thumbnail grid** (image-forward, how most lists are currently displayed)
- **text links** (a simple inline or bulleted list of wikilinks)
- **table** (columnar, for comparison)
- possibly a compact "chip"/inline-prose form

A v1 might only need to support the current thumbnail grid style.

Does the curator specify how a list is rendered? Or would the system automactially decide how to render based on information like whether the entity type supports images?

#### How lists are specified

Some options:

##### Inline

Specify each list inline in the markdown, such as some sort of fenced ` ```list ` block, or a `[[list:...]]` token the renderer expands in place. Prose flows around blocks at authored positions; a single `body` remains the whole Article; layout follows writing order.

Pros:

- TBD

Cons:

- TBD

##### Structured fields

Another option would be to make lists structured fields, where the body is pure markdown and lists are separate typed records the template slots into fixed regions.

Pros:

- TBD

Cons:

- Rigid layout: you can't put a grid _between_ two paragraphs

### Images

Content is more compelling with images. We want contributors to be able to put images into the Article. But we need to think through the use cases.

Some unorganized, unvetted thoughts:

- **Reference existing catalog media.** Point at an image already uploaded to a model, gameplay feature, etc. — reusing the existing claims-based media system. The image's attribution/credit travels with it.
- **Article-owned uploads.** Can you upload an image that belongs to the Article itself, not to any catalog entity? Such as a banner, a diagram, a period photo that isn't "of" one specific model. Mechanically this means the Article becomes a media-supported entity — it joins the model-driven media registry (`MediaSupportedEntityKey`) and gets its own media categories. We would NOT have a bespoke article-image table.
- **Display options.** Placement (banner across the top / inline in the prose flow / aside/float) and possibly size. Caption and credit line. The tension: the more layout control we expose, the more complexity we introduce and the more we drift from the principle of "semantic authoring, derived presentation".

### Sidebar

The site's current design is a two-column (main + sidebar) layout, where the sidebar disappears on mobile widths. Markdown currently only shows up in the main column. It would be cool if contributors could control what shows up in the sidebar, like putting lists there. However, we will NOT do anything that bakes our current two-column presentation into the content model, it has to be higher-level than that, and continue to work if we move to a different layout.

The answer to this may not apply to just Articles, but for all markdown content.

Some options:

- Automatic rules determine what shows up there, such as maybe any list automatically also shows up in the sidebar.
- The contributor marks some of the content as _secondary_ / _aside_ and that's what shows up in the sidebar. This might work well with things like: an aside image, a related-articles list, a key-facts box.

### Accordions

The site's current design uses accordions in the main content area. Today, markdown content is displayed within a single accordion section, often called "Overview". How does long-form content and list content (and images etc) interact with these accordions? As in [Sidebar](#sidebar), we must not bind our long term permanent content model to the current accordion UX.

The answer to this may not apply to just Articles, but for all markdown content.

Some options:

- **Auto-accordion `##` sections.** Every second-level heading becomes a collapsible section. Simple, predictable, no new authoring syntax. Every section is displayed open, not closed.
- **Per-section default-collapsed.** Let a specific section render collapsed by default (long appendix, tangential detail). Markdown has no native attribute for a heading, so this needs _some_ marker — a directive on the heading, a fenced attribute block, or metadata keyed by heading slug. Introduces authoring syntax; weigh against the "no markup to learn" goal from [RichText](../user_engagement/RichText.md).
- **Responsive divergence (collapsed on mobile, open on desktop).** Genuinely useful — long sections are more oppressive on a phone — but adds a per-breakpoint state axis.

### Credit

In order to incentivize contributors to write content like long form articles, I imagine they will want to be very publicly credited for having written the article. How might that work? An article cannot be attributed to a single person, like a byline on Kineticist, because all content on the site is collaborative by nature -- any contributor can edit any Article. But maybe we can put a more collaborative byline there. Maybe there's an Authors list, that lists each person involved.

However, this could be true of any content -- do we incent people to update pages because they are clearly credited? Why not have attribution on other entity pages? And why might we not want this feature anywhere -- I can imagine putting a byline will discourage other people from editing a page 'owned' by someone else. We need some clear product thinking on the Why and comparables around this.

### Timestamp

Most catalog pages do not display a last updated timestamp. However, it somehow feels like Articles should. This kind of goes with the [Credit](#credit) question. I imagine an attribution area somewhere near the top that says something like "Authors: J. Kurtz, #pam-wiles. Last updated 20 days ago."

However, this could be true of any content. Should we (or not) have attribution on other entity pages? We need some clear product thinking on the Why and comparables around this.

## Technical design

The design of the feature is TBD pending the product thinking above. Do not write this yet.

## Deferred

Things for future consideration.

### Backlinks

The Article's prose and lists link out to entities; each referenced entity could surface "Articles that mention me" or "other things that reference me" that includes non Article references.

### Page builder

Some sort of page builder / page layout tool. It would be semantic authoring with derived presentation, not pixel-perfect control.

If we _DID_ have some sort of builder in the future, it'd probably be a markdown builder that works for all markdown everywhere in the product, not a page builder specifically for Articles.

## Prior art

### Semantic MediaWiki

It has #ask inline queries render live lists/tables inside an otherwise-prose wiki page.

### Wikidata + Listeria

A bot maintains SPARQL-generated lists embedded in Wikipedia pages; the canonical "computed set as a section of an article."

### MediaWiki DynamicPageList (DPL)

The extension wikis actually use to generate lists from categories/criteria in-page.

### Obsidian Dataview

Markdown notes with an embedded query language producing lists/tables; nearly your exact "markdown + computed list block."

### Notion linked-database views

One flexible page type; filtered/sorted DB views drop in as blocks alongside prose.

### Logseq / Roam query blocks

Same idea, block-level queries inside a note.

### Wikipedia

- "List of X" articles + Categories — the manual-vs-automatic split (hand-curated list articles vs auto category membership) is exactly the dynamic-vs-handpicked axis.
- Infobox/navbox templates — reusable curated cross-links attached to many pages.

### BoardGameGeek GeekLists

User-curated, annotated lists of catalog items with prose; plus families/expansions relationships. Very close.

### Discogs

Music catalog with versions/variants relationships + user-built lists; mirrors your copy/variant modeling.

### MusicBrainz

Collections + a rich relationship graph over a community-edited catalog.

### IMDb lists

Editorial and user lists over a structured entity catalog.

### TV Tropes

Concept pages that are mostly curated, cross-linked lists of works wrapped in prose.

### Fandom / Wikia

Fan-maintained franchise catalogs; the low-barrier open-editing culture you're targeting.

### Atlas Obscura

Editorial articles over a catalog of entities with staff curation. This is already the tone reference in the [engagement landscape doc](../user_engagement/UserEngagementLandscape.md).
