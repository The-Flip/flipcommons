# Unique Features / Toys

We have a data modeling / domain modeling issue around unique features / toys.

Until recently, we hadn't represented unique features / toys in the system, despite seeing this information on manufacturer documents, aggregator websites, and in `model.extra_data` IPDB fields like Notable Features and Toys. But then a few things happened all at once.

We made the decision to represent all features of a model in gameplay_features, even if they do not affect gameplay, like "toppers". The idea is that, if we want to make the distinction later on that smoe features affect gameplay and others don't, it's fairly easy to go add that information to the gameplay_feature data model without revisiting to every model. I'm happy with this decision.

At the same time we also made the decision to use a manufacturer's verbatim wording for a feature unless it's extremely clearly a synonym. When in doubt, create a child feature. For example we created a manufacturer's branded "InvisiGlass" as a child of the generic "Anti-Reflection Playfield Glass". I'm a little uncomfortable with the aliases because it involves applying judgement rather than faithfully transcribing the manufacturer's words. But I still think it's probably the right call.

However, I think we then went too far: we started putting **unique** features into gameplay_features. Things like in patches/0219-houdini-features.yaml: stages, stage curtains, milk-cans, spirit-planchettes, steampunk-flippers. These unique features / toys are too granular. And then to keep toys identifiable within gameplay_features, we created a parent Toys gameplay_feature and parenting all those toys to that, but then AI sessions started assigning gameplay_feature: [toys] to models, rather than the actual toy.

## Options

### ❌ Rejected option: `gameplay_features`

We started down this path and I don't like it, for the stated cons.

#### Pros

- **Cross-title sharing is representable**. Models within a title often share unique features. For example, Cirqus Voltaire remake shares the Ringmaster, TOTAN 30th the genie lamp, the Fish Tales kit the fishing reel. A `model.unique_features` would make that link invisible; a node makes the models assert literally the same thing. This is deeply compelling.
- **Unique features become encyclopedia entries**. Rudy and the Ringmaster would have a detail page and "appears in" list, could have a descriptions written. This is deeply compelling.
- **No schema change**. It works with today's machinery — `gameplay_feature` namespace, counted membership, per-assignment cites, the whole patch/validate/snapshot loop. Data acquisition could start today; `model.unique_features` requires data model work. I discount this one: we want to do the best thing long term for the project here.

#### Cons

- **It pollutes the conceptual space**. It mixes things that are real features with things that are unique one-offs.
- **It pollutes lookups**. When a contributor tries to find a gameplay feature in the autosuggest typeahead to assign it, they have to potentially wade through a bunch of one-offs. They'll inevitably get it wrong, and bad data will creep in.
- **It blinds the duplicate-detection gate**. For real features, near-duplicates get caught because a new term should resolve to something existing — collision is the signal. For bespoke unique features, every new node legitimately resolves to nothing, so "Iron Throne" vs "Iron Throne ball lock" vs "throne toy" across three sessions produces three nodes and no check can object. This one is deeply worrying.
- **Long slugs**. A toy's substance is descriptive — "motorized animated interactive dragon", "talking head named Rudy". A `gameplay_feature` forces the prose into either a long name, a lossy name or a per-node description field… at which point you've written the text field anyway, just sharded across vocab entries.
- **Slug collisions**. Slugs _could_ collide (dragon, GoT vs. three other dragons) even if we don't have examples of it today.

### Option: `gameplay_features` + `kind`

Put a new `kind` or `type` field on `gameplay_feature` to represent:

- gameplay-altering features
- features that do not affect gameplay
- unique features
- toys (a subcategory of unique features)

#### Pros

- It allows us to show features that only affect gameplay
- Cross-title sharing is representable
- Unique features become encyclopedia entries
- Doesn't blind the duplicate-detection gate
- Allows us to build a detection gate that ensures disparate titles don't share unique toys

#### Cons

- Long slugs
- Slug collision
- Kind of forces us to build a detection gate that ensures disparate titles don't share unique toys

### Option: a new `unique_features` join table

#### Pros

- Cross-title sharing is representable
- Unique features become encyclopedia entries
- Doesn't blind the duplicate-detection gate
- Allows us to build a detection gate that ensures disparate titles don't share unique toys

#### Cons

- Long slugs
- Slug collision
- Kind of forces us to build a detection gate that ensures disparate titles don't share unique toys

### Option: `model.unique_features`

For some reason AI sessions keep suggesting to start with this and promote notable toys that deserve encyclopedia entries to gameplay features, but that's a hard no. I don't want that sort of messy dual existence. Either all or none get their own web pages.

### ❌ Rejected option: `model.unique_features` + `model.toys`

This copies IPDB's two-field split, but the data shows that IPDB hasn't itself used having two fields effectively. `ipdb.toys` is populated on only 294 of our 6,934 live models (4%) against 5,213 (75%) for `ipdb.notable_features`, and 287 of the 294 carry both — an afterthought field, not a taxonomy. The two leak into each other constantly:

- **Batman Forever** lists "Batwing Ball Cannon" verbatim in _both_ fields.
- **AC/DC** puts the bell and the cannon in both, worded differently each time.
- **Medieval Madness (Remake)** files "Exploding castle" under toys but the pop-up trolls — a textbook toy — under notable features.
- **White Water** has Bigfoot in toys and the whirlpool funnel in notable features.
- **Champion Pub** inverts it outright: toys holds a 400-character prose paragraph on the punching bag, mini-playfield and jump rope, while notable features holds "Flippers (2), Up-post between flippers, Autoplunger."

The prose problem is visible in the source data too: `ipdb.toys` averages 101 characters and 82 of the 294 values run past 120, so it is prose as often as it is a list.

If the boundary fails at 4% coverage across 294 records, our authors won't hold it across thousands. Two text fields buy the same ambiguity as one, with an extra decision per row.

### ❌ Rejected option: `model.unique_features` with option to represent as `gameplay_features`

AI sessions have suggested that every feature start out in with `model.unique_features` and promote notable features that deserve encyclopedia entries to gameplay features, but that's a hard no. I don't want that sort of messy dual existence. Either all or none get their own web pages.

### Option: original text field on `gameplay_features`

Have a field like `manufacturers_name` or `original_name` or `written_as` or `described_as` on the edge, similar to MusicBrainz's `credited as`. So the edge would be `original_name`: "InvisiGlass", `feature`: "Anti-Reflection Playfield Glass".

This would solve the verbatim wording problem but not the core problem.

## Proposal

Take a look at `/models/genesis` and its IPDB free text. Toys is a paragraph of description:

> An animation feature is found under a dark tinted window in the middle of the playfield. It is called the "Regenerator" and it holds the "Lifeforce". When "Lifeforce" is lit, a full-stroke shot on the vari-target launches the unveiling of the Lifeforce robot. This sequence uses an onslaught of flashers around the robot and behind the translite, to the music of Bach's Toccatta & Fugue (as found on Gottlieb's 1982 'Haunted House').

Also for Genesis, if you look at all the IPDB information, there's another unique feature to pull out, the photographic translite. It's partially in Notes, partially in Notable Features.

To display these on the models, I'm wondering if we should organize it something like as follows.

### `/models/genesis`

- **Unique features**:
  - Regenerator animation: ➡️ link to `/unique-features/12345/regenerator-animation` (FK or short ID, slug is decorative suffix)
    - An animation feature is found under a dark tinted window in the middle of the playfield. It is called the "Regenerator" and it holds the "Lifeforce". When "Lifeforce" is lit, a full-stroke shot on the vari-target launches the unveiling of the Lifeforce robot. This sequence uses an onslaught of flashers around the robot and behind the translite, to the music of Bach's Toccatta & Fugue (as found on Gottlieb's 1982 'Haunted House').
  - Photographic translite: ➡️ link to `/unique-features/54321/photographic-translite` (FK or short ID, slug is decorative suffix)
    - Artist Don Marshall did the black-and-white photographic translite. Ken Hale tinted the translite with photo oils to add color.
- **Credits** (no change from current system):
  - Art: Don Marshall
  - Art: Ken Hale
  - etc

### `/unique-features/12345/regenerator-animation`

- Browser title: Regenerator animation • Genesis (Gottlieb 1986) [+ "and N others" if > 1]
- Type of: [animation] ➡️ link to `/gameplay-features/animation` etc
- Description: same as above
- Models: list of models with this exact same unique feature (NOT all models with animation).
- Photos: photos specifically of this feature. The photos would also be under the model itself, in its own category. We wouldn't have to do this for v1.

### `/unique-features/54321/photographic-translite`:

- Browser title: Photographic translite • Genesis (Gottlieb 1986) [+ "and N others" if > 1]
- Type of: [photographic translite] ➡️ link to `/gameplay-features/photographic-translite` etc
- Description: same as above
- Models: list of models with this exact same unique feature (NOT all models with photographic translites).
- Photos: photos specifically of this feature. The photos would also be under the model itself, in its own category. We wouldn't have to do this for v1.

### `/gameplay-features/photographic-translite`

The description on the page would talk about photographic translite being a Gottlieb house style. This page would link to all models with the feature, such as:

- Lost World 1978 Bally
- Genesis 1986 Gottlieb
- Gold Wings 1986 Gottlieb
- Hollywood Heat 1986 Gottlieb
- Raven 1986 Gottlieb
- Rock Encore 1986 Gottlieb
- Monte Carlo 1987 Gottlieb
- Spring Break 1987 Gottlieb

Each of those models could have their own `/unique-features/NNN/photographic-translite`. For example, Lost World 1978 Bally would talk about "first machine to use a photographic backglass". Rock Encore 1986 would talk about "Ken Hale is the keyboard player shown on it".

### Game of Thrones (Stern 2015)

If different models have different variations of an unique feature, models with the same variation share a page.

`/unique-features/98765/animated-interactive-dragon-non-motorized`:

- Models
  - Game Of Thrones (Pro)

`/unique-features/56789/motorized-animated-interactive-dragon`:

- Models
  - Game of Thrones (Limited Edition)
  - Game of Thrones (Premium)

The only formal relationship between these two unique dragon features is their shared `type of: toy` or whatever gameplay feature they are a type of; there's no abstract parent model that doesn't actually exist on any model. The descriptions of each can wikilink to the other.

### Unique feature identity and merging

The row's identity is its ID. Duplicate names are expected, there is no uniqueness constraint on names.

One row per distinct physical instance, shared only when models literally have the same one. Merging two rows is a union of their models; splitting happens when a model turns out to have a different execution. Both are ordinary operations, not schema events.

#### Dedup gate

I don't think we can dedup gate on the unique feature's gameplay feature(s):

- AC/DC has the bell, the cannon, the train and the band diorama — plausibly all type of: animatronic toy.
- Genesis could have a second animation.

When a contributor is entering a unique feature, the typeahead autocomplete shows each item as `<feature name> • <model> (+ N others)`. Unique features already on sibling models of the same Title are ordered first. Creating a new unique feature with the same name is okay.

### Unique features attach model not title

Unique features only attach to Model. Not Title.

### Unique features are claim-controlled

- UniqueFeature's `name`, `description` and `type_of`
- The Model↔UniqueFeature attachment — a membership claim on `Model`, same shape as `gameplay_feature`, including count.

### Unique feature `type of`

M2M. Always points at gameplay features. Empty set is fine. Resist creating new gameplay features just to fill this out.

### Toys

Corollary: the `toys` tree _does_ get built out in gameplay features. Something like:

- toys
  - static toys decorative — never moves, ball never touches it
  - interactive toys
    - bash toys the ball strikes it
    - animatronic toys
    - pop-up toys rises from or drops below the playfield
    - ball-holding toys locks, holds or delivers balls

Examples:

- Ringmaster → [animatronic toys, pop-up toys]
- GoT Pro dragon → [bash toys]
- GoT Premium dragon → [bash toys, animatronic toys]
- A plastic figurine → [static toys]

### Unique feature `description` is required

Description must be required and non-empty, enforced by CHECK. Once a row can exist purely to annotate a generic feature, there is no notability bar left in the design — nothing stops a UniqueFeature per model per feature. "You have something to say about it" is the bar. Without it this drifts into Giant Bomb concept sprawl, which is a failure mode of every wiki that let concepts be created empty.

### Wikilinks

The wikilink authoring format should include the name, something like [[unique-feature:12345:photographic-translite]]. The storage format would contain just the ID, like every other wikilink. The save should validate not only the ID but also the name, to prevent mis-typing. This authoring format is transitory so the period the name has to match is pretty small: it gets hydrated out of the database, a user edits the record and it gets saved again.

### Data patches and ID format

Data patches must be able to set descriptions for existing unique features, and reference existing unique features from models. Data patches cross DBs and cannot know about a specific DB's IDs. This means the unique feature's public ID cannot be the Django database-generated `id` field, and data patches creating a unique feature should be able to supply an ID. `CitationInstance` already mints IDs like this (it calls them slugs) and we should copy that, including its digit-free alphabet.

The unique feature ID format in data patches should include the name, something like `abcdefg-photographic-translite`, and validate on it. This is not a problem: pata patches are transitory, and only need to be valid from the moment they are created until they're applied on prod.

Many example IDs in this proposal use numeric IDs, misleadingly; to reiterate, we will NOT use numeric IDs.

### Delete blocking

Deletion of a unique feature is blocked if any models point at it.

### Unique features and gameplay features double-encode the relationship

On a model page like GoT Premium, we might have these data elements:

- gameplay features: [bash toys, animatronic toys]
- unique features: GoT Premium dragon → [bash toys, animatronic toys]

The problem: nothing links `gameplay features: [bash toys, animatronic toys]` to the dragon, so people will wonder if they refer to something ELSE in the model.

Options to fix:

#### ❌ Rejected option: only set the gameplay features transitively

One way to fix would be to not set those gameplay features directly on the model, but only transitively via the unique feature. Cons:

- how do we tell contributors to NOT set those particular gameplay features? It's wrong to give them a value and then tell them not to use it, of COURSE they'll use it.
- when we do filtering by gameplay feature we now need to add the extra hops to unique feature and then to model

#### Accepted option: fix in the display

Render the model's feature list as the rollup, with named instances nested under what they're a type of:

```text
Bash toys (2)
└ GoT Premium dragon
└ (1 unnamed)
Animatronic toys (1)
└ GoT Premium dragon
```

### Filtering by gameplay feature

A contributor may set the unique feature but not the gameplay feature. We want the filtering by gameplay feature to work whether or not the gameplay feature is directly specified.

Implementation suggestion from an AI session, I have not vetted it: union the two sources into one set of (feature, model) pairs before the existing DAG rollup runs, so a query for bash toys returns GoT Premium whether the model claims bash toys itself, only its dragon does, or both. Because the union happens ahead of the descendant closure that backend/apps/catalog/api/\_counts.py:16 already applies, inheritance composes in both directions for free: the dragon's type_of: [bash toys] also makes the model match interactive toys and toys. Nothing is materialized and no traversal happens per-model — it's one additional bulk values_list over MachineModel → unique_features → type_of, folded into the same pair set the direct edge already produces.

### Branded names for generic features

Manufacturers give branded names to generic features, like InvisiGlass, Magic Glass, Expression Lighting. You might think that we'd make these unique features: unique feature InvisiGlass is type_of Glare-Reducing Glass. But no. Instead, they're gameplay features: gameplay feature InvisiGlass is type_of Glare-Reducing Glass. Reasons:

- **Brand names are unique**. GameplayFeature names are unique and UniqueFeature names aren't. But a brand name is unique by definition; that's what a trademark is. We want the second contributor who types "InvisiGlass" to hit the existing row and stop. Moving brands into unique features throws away the duplicate-detection gate.
- **Brand name description is about the product, not an instance**. `UniqueFeature.description` is required because "you have something to say about this instance." InvisiGlass's description — Stern's branded anti-glare glass, its coating, when it shipped — is identical on all 200 models. That's a vocabulary entry's description. And the page framing collapses too: "InvisiGlass • some arbitrary Stern (+199 others)" isn't a useful title.
- **Sprawl risk is bounded**. The pollution con that pushed toys out of the vocabulary doesn't apply here. Brand names for a generic feature are a small finite set per generic — InvisiGlass, Magic Glass, maybe a handful more under glare-reducing glass. A DAG with 3-10 children is what a DAG is for.

### Explicitly NOT doing

For the photographic translite scenairo, you might argue that that's a new `MachineModelGameplayFeature.note` field. No.

1. That would fragment these into a unique feature concept and a 'annotate a generic feature' concept. I suspect from a contributor's perspective they're the same activity: there's this feature on Gorgar I want to talk about, how do I do that.
2. Attaching photos to `MachineModelGameplayFeature` is hard.
