# The Flip's Manufacturer Timeline

## Context

The Flip museum built a manufacturer timeline poster off the public Flipcommons API and documented their surprises, workarounds and suggested changes in
[`docs/flipcommons-data-notes.md`](https://github.com/The-Flip/mfgtimeline/blob/main/docs/flipcommons-data-notes.md).

Since then, Flipcommons has shipped some things that would make making a new version of the manufacturer timeline poster more accurate and easier to implement.

## API shape

Flipcommons has entirely overhauled its public API.

The mfgtimeline was implemented against `/api/models/all/` and `/api/manufacturers/all/`. These
forced per-model detail fetches for the richer fields and a name→slug join. Flipcommons has since retired those endpoints and is offering two different options on how to work with the data: the [bulk export API](#bulk-export-api) or an [analytics package](#analytics-package).

### Bulk export API

Flipcommons has published **bulk export endpoints** that dump every record with all fields in one call. Also, the API docs are much more detailed. Also, there's now rate limiting, so save a copy of each response and use it locally. Rate limits are 120 requests/hour per IP shared across all export endpoints ≈ 6 full exports/hour.

Some key endpoints:

- `GET /api/export/models/`
- `GET /api/export/manufacturers/`
- `GET /api/export/corporate-entities/`

### Analytics package

Probably better than the Export API for an analysis-heavy project like `mfgtimeline` is to use our pre-packaged analytics. We can give you a DuckDB analytics database over the entire catalog. This is what we use on a daily basis to answer pinball data questions, and is better than the Export API because:

- **It is a semantic layer.**. It's a curated semantic layer rather than a mirror of the Django schema. Views respect soft-deletes, declare their grain, decode foreign keys to stable slugs and state the specific way it would otherwise hand you a confident wrong answer.
- **It is legible to an AI.** The relations and columns and inter-column relationships and reasoning traps to beware are extensively documented, so an AI pointed at the file reads what each relation means and which trap it carries instead of inferring intent from column names.
- **It includes IPDB and OPDB.** It includes the IPDB and OPDB corpus, attached to the correct records, making it very easy to analyze across the combined set.

This is not public; it's for inside-the-Flip only. For more details see [PackagedAnalytics.md](../analytics/PackagedAnalytics.md).

## The Flip "Surprises" (items 1–11)

### 1. Manufacturers consolidated, keyed by slug, no integer IDs: DONE

`/api/export/models/` now exposes not only the granular `corporate_entity` slug but also the `manufacturer` slug, so consumers no longer have to do the corporate_entity → manufacturer join themselves. Also the [analytics package](#analytics-package) auto-joins them.

There's still no integer ID and won't be. It's not needed.

### 2. No merger/succession relationships exposed: WONTFIX

Flipcommons will not model cross-brand lineage. The general principle: unless/until it's information Flipcommons actually displays, it won't be captured.

**Workaround**: The Flip already solved this with 5 curated JSON records, keep doing that.

### 3. Corporate-entity year fields all null: DONE (solved differently)

The Flip wanted the raw `year_start`/`year_end` incorporation/dissolution years populated.
Flipcommons went a different way.

Corporate years are misleading: a company can incorporate years before its first pinball machine or linger years after its last. We tried having AIs populate years and it actually created a mess _because_ the AIs got accurate corporate inception dates. We realized that what people actually care about is the years a manufacturer was actually making pinball.

So Flipcommons _removed_ the physical corporate year fields. Instead, there's now:

- `year_of_first_model` / `year_of_last_model` — computed from the production years of its
  (non-variant) models.
- `operating_status` — enum `ongoing` / `ended` / `unknown`. A manufacturer that is `unknown` and has not produced a machine in 6 years is treated as
  ended in the UI (an `unknown` manufacturer with a recent machine is still rendered open-ended). API clients like mfgtimeline should do the same.

These are included on `/api/export/corporate-entities/` and `/api/export/manufacturers/`, where
`operating_status` rolls up across a brand's entities (precedence ongoing > unknown > ended).
Within-brand transition years are still derivable — each entity's production span is its own —
without trusting corporate paperwork dates.

This information is also in [analytics package](#analytics-package).

### 4, 5 & 6. Manufacturer over-consolidation: MOSTLY DONE

Three items were the same underlying problem: Sega not being split the way `stern-electronics` / `stern-pinball` is, bad consolidations and stray early machines, and the `bally` brand carrying a German corporate entity (Bally Wulff) so that resolving one region for the brand surfaced Germany alongside the US.

Over-consolidation turned out to be widespread and we fixed it systematically. A lot got separated. For example:

- `bally-wulff` is now its own brand (Germany, 12 models, 1979–87). After research we came around to The Flip's position: people say "it's a Bally Wulff game." `bally` now resolves cleanly to the US across all three of its corporate entities.
- `taito-do-brasil` is its own brand (32 models, 1975–83), separate from `taito`.
- `sonic` is separate from `segasa`, though both are Spain.
- `stern-electronics` (1977–82) and `stern-pinball` (1999– ) remain separate, as The Flip noted was already correct.
- Stray early machines fixed: the `stern-electronics` 1932 misattribution (Western/Northwestern/Southwestern lumps), the `midway` 1932 stray, the `williams` 1933 stray, the `united` 1933 "Bank A Ball" stray. Separately, `american-pinball`'s LoV Deluxe LE was re-dated 2012→2021.

#### Ones we'd like to debate

- **"Taito isn't a Chicago company."** My understand is that it partly is. The `taito` brand has two corporate entities: `taito-trading-co-ltd` (Japan, 1967) and `taito-america-corporation` in Elk Grove Village, Illinois — and produced two games, Ice Cold Beer (1983) and Zeke's Peak (1984). Our read is that people call those Taito machines rather than Taito America machines, so the brand legitimately has a Chicago-area presence.
- **"1970s Sega shouldn't be lumped with 1990s Sega."** As far as I can tell, people call all of them Sega machines regardless of era.

#### Workaround for anything still consolidated that The Flip disagrees with

Keep the handwritten JSON override.

### 7. No production-status flag (The Flip's "big one"): DONE

The issue: the timeline only considers commercially produced machines, but Flipcommons
gave no way to tell them apart; prototypes carried no marker, `production_quantity` was blank
for most, and a known unreleased game like Mazatron looked identical to a shipped title.

This exposed a real hole in the Flipcommons (and IPDB) data. To solve it, Flipcommons added `Model.production_status`:

- `produced` — commercially produced.
- `announced` — announced by the manufacturer but not in production.
- `unreleased` — intended for production but cancelled, shelved or abandoned.
- `one-off` — manufacturer-built single unit, never meant for sale (gifts, props, test pieces).
- `aftermarket` — modified by someone other than the manufacturer (fan re-themes, modders).

Like `game_format` below, it's a controlled vocabulary rather than a fixed enum, so a model row carries the slug and `GET /api/export/production-statuses/` is the list, with a written description of each value.

A good chunk of the world's non-`produced` models have now been marked as such. All five of The Flip's named prototypes — Mazatron, Pinball Circus, King Kong, Big Bang Bar, Kingpin — are set `unreleased`.

We have NOT set `produced` on any models yet because we're still finding more non-produced ones. At some point we'll flip the remaining ones en-masse to `produced`. But for now, `production_status` = `null` OR `produced` is a good approximation of all the actually produced models.

### 8. Conversion kits counted as machines: WONTFIX

The `conversion-kit` tag has been retired. Models returned by `/api/export/models/` now carry a `model_relationships` array; a conversion kit has an edge whose `relationship_type` is `conversion_kit`. This keeps kit-ness separate from `production_status`: an official kit can be `produced`, while an unofficial one can be `aftermarket`.

**Workaround**: filter out models with any `model_relationships` entry whose `relationship_type` is `conversion_kit`.

**To discuss**: it's a hassle to do this filtering: you must first spend quite a lot of time understanding the relationships, THEN design the filtering. We're considering having a public filter/search API. It would return model and title slugs, and consumers would get the details of each record from their cached copy of the Export API results.

### 9. Aftermarket re-themes attributed to the original manufacturer: DONE

Re-themes went the same way conversion kits did: they're edges now, not tags. A re-theme carries a `model_relationships` entry whose `relationship_type` is `retheme`, pointing at the donor machine it re-skins. Whether the manufacturer authorized it is a separate `license_status` field on that edge (`licensed` / `unlicensed` / `unknown`) rather than two different kinds of re-theme — though in practice it's still `unknown` on nearly all of them.

You shouldn't need any of that to decide what was produced commercially, though. There are 38 re-themes in the catalog and 37 of them also carry `production_status` = `aftermarket`, so the production-status filter already excludes them.

### 10. `/api/models/?game_format=` returned 0 for every value: DONE

The issue: the `game_format` field was completely unpopulated, so it was useless as a filter.

Flipcommons has now classified over 500 non-pinball models. The `game_format` vocabulary so far:

- `pinball`
- `bagatelle`
- `shuffle`
- `pitch-and-bat`
- `slot-machine` (new)
- `video-game` (new)
- `gun-game` (new)
- `bingo-pinball` (new)
- `one-ball` (new)
- `rolldown` (new)
- `miscellaneous` (new)

`bingo-pinball` is much the largest of these, at over 300 models — bingos are pinball's gambling cousin, and a timeline that means "pinball machines" almost certainly wants them out. It's the single biggest thing this classification buys you.

Same vocabulary story as `production_status`: expect the list to keep growing, and read it from `GET /api/export/game-formats/`, where each entry carries a written description of what the format actually is — worth reading for `miscellaneous` in particular, which is deliberately a catch-all.

A good chunk of the non-pinball games have now been marked as such. Most models remain unclassified because we keep finding more non-pinballs, so `game_format` = `null` OR `pinball` is still a good approximation of pinball machines.

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

Places to see this:

<https://flipcommons.org/changesets> is the global feed of every change to the catalog, every change's citations and quotes.

Each record also has its own Sources page, like <https://flipcommons.org/models/cactus-canyon-continued/sources>. It lists every field on the record, the distinct values that have been asserted for it, who backs each one and the citations behind them, with the values that lost the conflict shown de-emphasized beneath the winner. That last part is the bit worth looking at: it's not just what Flipcommons says, it's what the alternatives were and why this one won.

## Potential new issues

### Can't filter from public API

The publicly documented API no longer includes the APIs The Flip was using to filter, such as `/api/models/?game_format=`. They still exist at the same location and you can still hit them, but they're not in the API docs. This was done to prevent 3rd parties from building real-time integrations to Flipcommons. Export data infrequently good, constantly hit system bad. For The Flip, using the [analytics package](#analytics-package) would solve this comprehensively. LMK if you think omitting them from the public API is a questionable call.

I don't mind The Flip hitting the unpublished APIs, though.
