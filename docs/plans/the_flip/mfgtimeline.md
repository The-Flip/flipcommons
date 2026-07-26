# The Flip's Manufacturer Timeline

## Context

The Flip museum built a manufacturer timeline poster off the public Flipcommons API and documented their surprises, workarounds and suggested changes in
[`docs/flipcommons-data-notes.md`](https://github.com/The-Flip/mfgtimeline/blob/main/docs/flipcommons-data-notes.md).

Since then, Flipcommons has shipped some things that would make making a new version of the manufacturer timeline poster more accurate and easier to implement.

## API shape

Flipcommons has entirely overhauled its public API.

The mfgtimeline was implemented against `/api/models/all/` and `/api/manufacturers/all/`. These
forced per-model detail fetches for the richer fields and a name→slug join. Flipcommons has since hidden those endpoints (they're now for internal Flipcommons website use) and instead published **bulk export endpoints** that dump every record with all fields in one call. Also, the API docs are much more detailed now. Also, there's now rate limiting, so save a copy of each response and use it locally.

Some key endpoints:

- `GET /api/export/models/`
- `GET /api/export/manufacturers/`
- `GET /api/export/corporate-entities/`

## The Flip "Surprises" (items 1–11)

### 1. Manufacturers consolidated, keyed by slug, no integer IDs: DONE

`/api/export/models/` now exposes not only the granular `corporate_entity` slug but also the `manufacturer` slug, so consumers no longer have to do the corporate_entity → manufacturer join themselves.

There's still no integer ID and won't be. It's not needed.

### 2. No merger/succession relationships exposed: WONTFIX

Flipcommons will not model cross-brand lineage. The general principle: unless/until it's information Flipcommons actually displays, it won't be captured.

**Workaround**: The Flip already solved this with 5 curated JSON records, keep doing that.

### 3. Corporate-entity year fields all null: DONE (solved differently)

The Flip wanted the raw `year_start`/`year_end` incorporation/dissolution years populated.
Flipcommons went a different way.

Corporate years are misleading: a company can incorporate years before its first pinball machine or linger years after its last. We tried having AIs populate years and it actually created a mess _because_ the AIs got accurate corporate inception dates. We realized that what people actually care about is the years a manufacturer was actually making pinball.

So Flipcommons _removed_ the physical corporate year fields entirely. Instead, there's now:

- `year_of_first_model` / `year_of_last_model` — computed from the production years of its
  (non-variant) models.
- `operating_status` — enum `ongoing` / `ended` / `unknown`. Many manufacturers are explicitly set
  `ended`. A manufacturer that is `unknown` and has not produced a machine in 6 years is treated as
  ended in the UI (an `unknown` manufacturer with a recent machine is still rendered open-ended). API clients like mfgtimeline should do the same.

These are included on `/api/export/corporate-entities/` and `/api/export/manufacturers/`, where
`operating_status` rolls up across a brand's entities (precedence ongoing > unknown > ended).
Within-brand transition years are still derivable — each entity's production span is its own —
without trusting corporate paperwork dates.

### 4. Stern is two companies (correct); Sega the museum split: WONTFIX???

The Flip wants Sega to be split like `stern-electronics` / `stern-pinball` is split, where the 1990's Chicago era and the 1970's Japan era are different manufacturers aka brands.

Let's talk. Unlike Stern, where they were always separate companies with separate brands, don't people consider 1970's Sega and 1990's Sega to be the same brand?

**Workaround**: The Flip keeps its JSON file override.

### 5. Bad consolidations / stray early machines: DONE

Fixed:

- `stern-electronics` 1932 misattribution (Western/Northwestern/Southwestern lumps).
- `midway` 1932 stray, `williams` 1933 stray.
- `united` 1933 "Bank A Ball" stray.
- `american-pinball` LoV Deluxe LE mis-dated 2012→2021.

### 6. "Bally Wulff" makes Bally look German: WONTFIX

The issue was that the `bally` manufacturer consolidates a German corporate entity
(Bally Wulff), so resolving a single region for the brand surfaces Germany alongside the US.

That consolidation stands: `bally-wulff` still has `manufacturer_slug: bally`, and Flipcommons
does not expose one canonical region per brand — region is derived from the corporate entities'
locations, so "Bally" inherently carries every member's country.

**Workaround**: consumers that want one region per brand must pick the dominant one (US), exactly as The Flip already does (`classify_region` lets US win).

### 7. No production-status flag (The Flip's "big one"): DONE

The issue: the timeline only considers commercially produced machines, but Flipcommons
gave no way to tell them apart; prototypes carried no marker, `production_quantity` was blank
for most, and a known unreleased game like Mazatron looked identical to a shipped title.

This exposed a real hole in the Flipcommons (and IPDB) data. To solve it, Flipcommons added a `Model.production_status` enum:

- 0 `produced` — commercially produced.
- 3 `announced` — announced by the manufacturer but not in production.
- 111 `unreleased` — intended for production but cancelled, shelved or abandoned.
- 10 `one-off` — manufacturer-built single unit, never meant for sale (gifts, props, test pieces).
- 39 `aftermarket` — modified by someone other than the manufacturer (fan re-themes, modders).

A good chunk of the world's non-`produced` models have now been marked as such. All five of The Flip's named prototypes — Mazatron, Pinball Circus, King Kong, Big Bang Bar, Kingpin — are set `unreleased`.

We have NOT set `produced` on any models yet because we're still finding more non-produced ones. At some point we'll flip the remaining ones en-masse to `produced`. But for now, `production_status` = `null` OR `produced` is a good approximation of all the actually produced models.

I'm considering this done enough for now.

### 8. Conversion kits counted as machines: WONTFIX

The `conversion-kit` tag has been retired. Models returned by `/api/export/models/` now carry a `model_relationships` array; a conversion kit has an edge whose `relationship_type` is `conversion_kit`. This keeps kit-ness separate from `production_status`: an official kit can be `produced`, while an unofficial one can be `aftermarket`.

**Workaround**: filter out models with any `model_relationships` entry whose `relationship_type` is `conversion_kit`.

### 9. Aftermarket re-themes attributed to the original manufacturer: DONE

Flipcommons now separates rethemes into `unofficial-retheme` and `manufacturer-retheme` tags. The 37 models tagged `unofficial-retheme` also have `production_status` = `aftermarket`, so I don't believe you need to look at rethemes to figure out whether the machine was produced commercially.

### 10. `/api/models/?game_format=` returned 0 for every value: DONE

The issue: the `game_format` field was completely unpopulated, so it was useless as a filter.

Flipcommons has now classified ~170 non-pinball models. The `game_format` vocabulary so far:

- 2 `pinball`
- 16 `bagatelle`
- 21 `shuffle`
- 16 `pitch-and-bat`
- 51 `slot-machine` (new)
- 7 `video-game` (new)
- 5 `gun-game` (new)
- 54 `miscellaneous` (new)

A good chunk of the non-pinball games have now been marked as such. As with `production_status`, the `pinball` value is not set yet because we keep finding more non-pinballs. But you get a pretty good approximation of pinball machines by `game_format` = `null` OR `pinball`.

I'm considering this done enough for now.

### 11. Join + null quirks: PARTIAL

#### models exposed only `manufacturer_name`, not the slug: DONE

**Issue**: linking a model to its manufacturer meant joining on the display name.
**The fix**: the manufacturer export API now includes the `manufacturer` slug directly, use that for the join.

#### empty locations for Gottlieb, Data East: DONE

Locations for those manufacturers are now present.

However, there's still a lot of smaller manufacturers without locations.

#### ~1,300 null `year`: UNDONE

This remains TODO. It's a pretty hard data acquisition problem. The data is not in IPDB or OPDB.

#### ~70 null `manufacturer_name`: UNDONE

This remains TODO. It's a pretty hard data acquisition problem. The data is not in IPDB or OPDB.

### Early Japanese manufacturers: DONE

**The issue**: Flipcommons is thin on early Japanese pinball. The Flip cross-checked against the thetastates.com/eremeka catalog of early Japanese flipper games and found manufacturers that Flipcommons doesn't surface at all.

**Resolution**: Flipcommons imported the eremeka catalog plus info from a few other Japanese sources:

- `nihon-tenbo` now exists as a manufacturer carrying all 6 of its eremeka games
- The Sankyos were deliberately _not_ merged into one `sankyo` brand; instead all 9 of eremeka's Sankyo games now sit under the existing `sankyo-seiki` spanning 1969–76, with the placeholder/null years fixed.
- We added gap-fill models and year-fixes under Komaya, Universal, Nihon Gorakuki and Game Mate.

## Bonus: all data changes are cited

Every new piece of information discussed here was added to the system not only with citations that have links, but also verbatim quotes from those links. Not only that, adversarial AIs vetting those quotes for semantic accuracy until I'm pretty sure all citations actually prove the info being cited.

You can see the granular changes and their backing quotes at <https://flipcommons.org/changesets> ; currently you have to go to an individual record's change page ( like <https://flipcommons.org/models/cactus-canyon-continued> ) to see the detailed citation, but we'll probably include that info on the global page soon.

## Potential new issues

### Can't filter from public API

The publicly documented API no longer includes the APIs The Flip was using to filter, such as `/api/models/?game_format=`. They still exist at the same location and you can still hit them, but they're not in the API docs. This was done to prevent 3rd parties from building real-time integrations to Flipcommons. Export data infrequently good, constantly hit system bad. LMK if you think omitting them from the public API is a questionable call.

I don't mind The Flip hitting the unpublished APIs, though.
