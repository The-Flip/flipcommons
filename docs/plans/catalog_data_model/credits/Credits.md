# Credits

## Context

We need to revamp how we model how we give credit on games.

To take an example, Multimorphic's website for Portal (2025) shows these credits:

- **Creative Director**: Stephen Silver and Ian Harrower
- **Voices**: Jeff Hays
- **Cabinet Artist**: Luciano Fleitas
- **Playfield Artist**: Brad Albright
- **Art Direction**: Stephen Silver and Brad Albright
- **Sculpts**: Stumblor Pinball
- **Digital Assets**: Renegade Game Studios

Two problems:

1. **[Roles](#roles)**. Our vocabulary is currently limited to the following roles: `design`, `mechanics`, `software`, `art`, `animation`, `music`, `sound`, `concept`, `voice` and `other`. We cannot express finer shades of meaning like `Creative Director`, `Cabinet Artist`, `Playfield Artist`, `Art Direction` and `Sculpts`.
2. **[Credited parties](#credited-parties)**. Two of those credits aren't people. `Sculpts: Stumblor Pinball` and `Digital Assets: Renegade Game Studios` are companies. Our credit identity is `{person, role}`.

Our existing roles are IPDB's credit schema, verbatim. IPDB machine pages carry "Design by / Art by / Dots-Animation by / Mechanics by / Music by / Software by / Sound by". This taxonomy was built for 1975–1995 machines, where a game genuinely did have one designer, one artist, one sound person. IPDB itself handles everything outside the seven by dumping it into free-text Notes.

## History

The gap is concentrated by era, tracking how the industry's teams grew.

**EM and early solid state (pre-1990).** The seven roles are adequate, because the sources themselves have no more granularity. There is nothing to lose here. Many machines of this era carry only a design and an art credit, and plenty carry nothing at all.

**WPC-era Williams/Bally (1990s).** Already richer than IPDB records. Manuals and in-game credit screens separated mechanical engineering from electrical/hardware engineering, game programming from system software, and dot artist from playfield artist. IPDB flattened that, but the information exists in the manuals and on the credit screens.

**2010 to present.** Stern, Jersey Jack, American Pinball, Spooky, Multimorphic, Chicago Gaming, Haggis, Pinball Brothers, Barrels of Fun, and the homebrew scene routinely credit 15–40 people across 10–25 distinct labels per machine. This is where the model breaks. It is perhaps 400–700 machines — small in count, but large in credit volume, and it covers the machines people are most actively curious about.

## Where to find this information

The deep credit data is on manufacturer sites and in manuals, not in any aggregator. No pinball catalog has collected it.

## Roles

### Multiple inheritance

The natural model is a role hierarchy with rollup: `Cabinet Art` is a kind of `Art`, so filtering for people by the `Art` role would also return people credited with `Cabinet Art`.

It's multiple inheritance:

- `Art Director` is both `Art` and `Management`.
- `Cabinet Sculping` would multiple inherit from `Cabinet Art` and `Sculpting`

Both Gameplay Features and Themes already use multiple inheritance in our catalog, this would look just like them.

Modeling options:

- **Multiple inheritance / DAG**: `Art Director` = `Art` + `Direction`.
  - Pros: themes and gameplay features already work this way.
  - Cons: no credit system in the prior art does it.
- **Facets**: `Art Director` role = discipline node (`Art`) + function modifier (`Director`)
- Pros:
  - Other people do this, like MusicBrainz
- Cons:
  - New machinery
  - When we find a new dimension (like `Cabinet Sculping` would multiple inherit from `Cabinet Art` and `Sculpting`), we're back to multiple inheritance

### Hierarchy

Thoughts about a potential role hierarchy. This is listed as a top-down tree because that's easiest in a doc; that does not mean there's not multiple inheritance. This will be fleshed out / falsified by looking at the actual data.

#### Concept

The overall concept of the game.

IPDB lists `concept` as a separate thing from `design`, so I'm loth to put it under `Game Design`.

#### Game Design (alias: Design)

The overall design of the game, how it plays, NOT the design of the art. The current `design` credit maps to this.

#### Rules

#### Art

**Surfaces**: cabinet, playfield, backglass/translite, plastics, apron
**Techniques**: 3D modeling, sculpting, illustration

`Cabinet Sculping` would multiple inherit from `Cabinet Art` and `Sculpting`

##### Animation

###### Dot animation

###### Video/FMV

#### Audio

##### Sound design (alias: Sound)

##### Music

Bands go under here.

###### Composer

#### Voice

Essentially every speech-capable machine from 1980 onward has it. It's frequently the celebrity credit that draws searches.

#### Engineering

##### Electrical engineering

##### Mechanical engineering aka Mechanics

##### Software engineering

**Rules versus code.** Modern teams credit rules separately from software, and the distinction is real — a rules designer who does not write the firmware.

#### Light show

A genuinely new discipline with no ancestor among the seven.

#### Production and direction

Creative director, producer, project manager, art direction, writing and story.

#### Seniority

Lead, assistant, additional, co-, supervising.

`Additional Art` is `Additional` and `Art`.

#### Testing

##### QA

##### Playtesting

### Number of roles

Rough order-of-magnitude off-the-cuff guesstimate from one AI session: normalizing every raw credit label across manufacturer sites and manuals would give roughly 150–250 distinct source strings collapsing to roughly 30–45 canonical roles, with about 15 covering 90% of credits.

### Role aliases

To assist with deduping and scraping from 3rd party sites, a Role will need to be able to have aliases, as it is for Themes.

## Credited Parties

Not just companies — bands too. "Music by Metallica" (or Iron Maiden, AC/DC, Rush) is an extremely common credit on licensed music titles, and a band is neither a person nor comfortably a corporate entity. It is the case that most resists a person-only model, and also the case that sits least comfortably in a company-shaped one.

The non-person credits fall into these categories:

- **Contract studios** — Stumblor Pinball for sculpts, Zombie Yeti for art, and similar. The Portal case.
- **Design studios that are one person wearing a corporate hat** — Pat Lawlor Design is credited as an entity on Stern games. The person/company boundary is genuinely fluid, and sources pick one or the other arbitrarily.
- **IP holders supplying assets** — Renegade Game Studios on Portal: a licensee handing over digital assets. Common on licensed titles.
- **Bands and musical acts.**
- **Contract manufacturing and platform development** — Multimorphic's P3 has third-party developers shipping games on someone else's platform; Chicago Gaming builds remakes under license.

The double-entry hazard is the reason to reach for Corporate Entity or Manufacturer rather than inventing a separate "credited company" kind. The direction of travel is one-way and common: a contract studio becoming a manufacturer is roughly the boutique-manufacturer origin story, and a manufacturer doing contract work for another manufacturer also happens. Anything modeling credited companies as a kind distinct from manufacturers will need a merge story eventually.

## Versions

**Version-scoped credits**. Rulesets get rewritten post-release by different programmers. We don't currently represent versions within a model.

## Prior Art

### Pinball catalog sites

Pinball-specific sites are not ahead of us.

#### IPDB

The seven roles, plus free-text Notes as the escape hatch for everything else. This is our source.

#### OPDB

Carries essentially no credit modeling at all; it is identity and metadata.

#### Pinside

Game-page credits are largely IPDB-derived, so the same seven.

### Non-pinball prior art

#### MobyGames

Video games, and the closest analogue. Does exactly what is proposed here: hundreds of raw role strings normalized into a hierarchy of role groups and roles, with rollup search.

#### IMDb

Keeps people credits and company credits as separate relations — cast and crew versus a distinct Company Credits section covering production companies and VFX houses. Precedent for not shoehorning companies into the person table.

#### MusicBrainz

The most directly useful. Relationship types form a hierarchy with rollup, _and_ the credited party is an `artist` carrying a type of Person, Group, Orchestra, Choir, Character, or Other. That is a single credited-party abstraction that admits non-persons, which handles the Metallica case cleanly.

#### Discogs

The cautionary tale: near-free-text role strings, and the resulting vocabulary is a swamp.

#### BoardGameGeek

Links designers, artists, and publishers as distinct entity types.

#### CRediT

The Contributor Roles Taxonomy used in academic publishing. Fourteen flat roles, no hierarchy — and notably it includes `Supervision` and `Project administration` as peers of the discipline roles rather than as a separate management branch. Its answer to a cross-cutting credit is to **give the person two roles**: someone who both produced the figures and supervised gets `Visualization` and `Supervision`, not a single combined node. That is a third strategy alongside multiple inheritance and facets — decompose the source label into multiple credits on the same party. The cost is that the original label ("Art Director") is no longer reconstructable unless the raw source string is kept alongside.

#### MARC relator codes

The Library of Congress contributor-role vocabulary, roughly 300 terms. It is the cautionary tale from the opposite direction to Discogs: not free text, but a large, carefully controlled, and **entirely flat** list. The absence of any hierarchy or rollup is a long-standing complaint against it. Scale alone does not substitute for structure.
