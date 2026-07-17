# Rethemed models

A **re-theme** keeps another machine's gameplay and re-skins it with new art and theme. Right now we have tags for `unofficial-retheme` and `metallica-retheme`, but that's lossy; it misses the relationship: what's the model that was rethemed? Let's represent that as structured data.

## The proposal

Let's make this a new `relationship_type` called `retheme` in the `ModelRelationships` join table.

The primary reason: [The data](#the-data) shows one model -- Actros Magic Tour 2013 -- can be rethemed from one of TWO different models. Two rows in the join table. Otherwise, we'd more strongly consider representing this as dedicated columns on MachineModel: `official_retheme_of` and `unofficial_retheme_of`.

### Targets

Every rethemed machine must have a `target_machine` and never a `target_label`: it's inconceivable that the donor model isn't known on a retheme. [The data](#the-data) shows we have 100% knowledge of existing retheme donors.

This will require some new work on relationships, to represent that a target module is required.

### License status

As far as the `license_status` column of the join table, we can safely say that a retheme within the same maker is licensed, but I don't think we can safely permanently say that a retheme outside the maker is unlicensed. [The data](#the-data) indicates that other-maker rethemes carry no licensing info in their free text... but I'm not willing to automatically insert that into the data model in a way that codifies that information in the data. I suggest for now, though, that we _DO_ hide the license status input in the model relationships editor. All rows will have null `license_status`.

This will require some new work on relationships, to represent that license status cannot be entered.

## The data

The following table contains every model tagged `unofficial-retheme` or `manufacturer-retheme` in the local dev database.

- **License words**: whether free text contains any licensing-related word
- **Donor model** (and the donor maker): retrieved from free text

The donor model, the donor's maker and the licensing-word flag are read from the IPDB free text in `extra_data` (`ipdb.notes` / `ipdb.notable_features`); IPDB records the donor with a fixed phrasing — _"This is a re-themed game. It used to be `<Maker>`'s `<year>` '`<Donor>`'."_ An em dash (—) means empty/none.

| Retheme model               | Retheme maker               | Current tag            | License words | Donor model                  | Donor maker  |
| --------------------------- | --------------------------- | ---------------------- | ------------- | ---------------------------- | ------------ |
| Actros Magic Tour 2013      | —                           | `unofficial-retheme`   | —             | Volcano                      | Gottlieb     |
| Actros Magic Tour 2013      | —                           | `unofficial-retheme`   | —             | Mars God of War              | Gottlieb     |
| Alabama Crimson Tide        | —                           | `unofficial-retheme`   | —             | Target Alpha                 | Gottlieb     |
| Aloha                       | —                           | `unofficial-retheme`   | —             | Rainbow                      | Williams     |
| Asterix                     | —                           | `unofficial-retheme`   | —             | Jungle Queen                 | Gottlieb     |
| Big Dick                    | Fabulous Fantasies          | `unofficial-retheme`   | —             | Big Deal                     | Williams     |
| Big Healey                  | —                           | `unofficial-retheme`   | —             | Pat Hand                     | Williams     |
| Boston Red Sox              | —                           | `unofficial-retheme`   | —             | Straight Flush               | Williams     |
| Budapest                    | —                           | `unofficial-retheme`   | —             | Rawhide                      | Stern        |
| Chingy                      | —                           | `unofficial-retheme`   | —             | Black Belt                   | Bally Midway |
| Energie IV                  | —                           | `unofficial-retheme`   | —             | Mariner                      | Bally        |
| Fraggle Rock                | —                           | `unofficial-retheme`   | ✅            | The Flintstones              | Williams     |
| Funtime Frankie             | —                           | `unofficial-retheme`   | —             | The Wiggler                  | Bally        |
| Gas Attack                  | —                           | `unofficial-retheme`   | —             | Breakshot                    | Capcom       |
| Go Girl!                    | —                           | `unofficial-retheme`   | —             | Earthshaker                  | Williams     |
| Grosse Pointe               | —                           | `unofficial-retheme`   | —             | Swords of Fury               | Williams     |
| Iron Maiden                 | —                           | `unofficial-retheme`   | —             | Gorgar                       | Williams     |
| Iron Maiden II              | —                           | `unofficial-retheme`   | —             | F-14 Tomcat                  | Williams     |
| Last Supper                 | —                           | `unofficial-retheme`   | —             | Cabaret                      | Williams     |
| Lucky Luke                  | —                           | `unofficial-retheme`   | —             | Fast Draw                    | Gottlieb     |
| Metallica (Retheme)         | —                           | `unofficial-retheme`   | —             | Earthshaker                  | Williams     |
| Mini Cooper S               | —                           | `unofficial-retheme`   | —             | Grand Prix                   | Williams     |
| Muscle Car Cafe             | Fabulous Fantasies          | `unofficial-retheme`   | —             | Nitro Ground Shaker          | Bally        |
| Naruto                      | —                           | `unofficial-retheme`   | —             | Force II                     | Gottlieb     |
| Night Club                  | —                           | `unofficial-retheme`   | —             | Dogies                       | Bally        |
| Pittsburgh Penguins         | —                           | `unofficial-retheme`   | —             | Dragon                       | Interflip    |
| Queen                       | —                           | `unofficial-retheme`   | —             | Flash Gordon                 | Bally        |
| School Girl Reaper          | —                           | `unofficial-retheme`   | —             | Flip Flop                    | Bally        |
| Sea Nymph                   | —                           | `unofficial-retheme`   | —             | Georgia                      | Williams     |
| Shrek                       | Stern Pinball, Incorporated | `manufacturer-retheme` | ✅            | Family Guy                   | Stern        |
| Slamdunk                    | —                           | `unofficial-retheme`   | —             | Space Invaders               | Bally        |
| Sunset Riders               | —                           | `unofficial-retheme`   | —             | Eight Ball                   | Bally        |
| The French Connection       | —                           | `unofficial-retheme`   | —             | Super Nova                   | Game Plan    |
| The Hellacopters            | —                           | `unofficial-retheme`   | —             | King Pin                     | Gottlieb     |
| Trump's Secret Service      | —                           | `unofficial-retheme`   | —             | Secret Service               | Data East    |
| Udo Lindenberg              | —                           | `unofficial-retheme`   | —             | Harlem Globetrotters On Tour | Bally        |
| Verspiel Dein Wasser nicht! | —                           | `unofficial-retheme`   | —             | Strikes and Spares           | Bally        |
| Wonder Woman                | —                           | `unofficial-retheme`   | —             | Lectronamo                   | Stern        |
| grand theft auto vice city  | —                           | `unofficial-retheme`   | —             | Hollywood Heat               | Premier      |

The two licensing-word hits, verbatim from `ipdb.notes`:

- **Fraggle Rock** (`license`): "…this glass was not made by Bally, nor did Bally seek a license for it." (about the backglass/logo)
- **Shrek** (`licensing`): "…nailing down the licensing of Smash Mouth's 'All Star'…" (about the game's music)

### Recreating / validating

Structured columns (retheme model, retheme maker, tag) and the raw donor-bearing note, straight from the dev SQLite database (`backend/db.sqlite3`):

```sql
SELECT
  m.name                                          AS retheme_model,
  COALESCE(ce.name, '')                           AS retheme_maker,
  t.slug                                          AS current_tag,
  json_extract(m.extra_data, '$."ipdb.notes"')    AS ipdb_notes
FROM catalog_machinemodel m
JOIN catalog_machinemodel_tags mt ON mt.machinemodel_id = m.id
JOIN catalog_tag t                ON t.id = mt.tag_id
LEFT JOIN catalog_corporateentity ce ON ce.id = m.corporate_entity_id
WHERE t.slug IN ('unofficial-retheme', 'manufacturer-retheme')
ORDER BY m.name;
```

Donor model and donor maker are extracted from `ipdb_notes` with the pattern `used to be <Maker>'s <year> '<Donor>'` (note that makers ending in _s_, e.g. Williams, use a bare apostrophe: `Williams' 1948 'Rainbow'`; Actros names two donors; Shrek states its donor in prose — "used the existing Family Guy pinball game design").

Licensing-word scan, restricted to the two free-text fields so metadata keys like `ipdb.image_urls.__license_id` don't produce false positives:

```sql
WITH r AS (
  SELECT m.name,
         lower(
           coalesce(json_extract(m.extra_data, '$."ipdb.notes"'), '') || ' ' ||
           coalesce(json_extract(m.extra_data, '$."ipdb.notable_features"'), '')
         ) AS ftext
  FROM catalog_machinemodel m
  JOIN catalog_machinemodel_tags mt ON mt.machinemodel_id = m.id
  JOIN catalog_tag t                ON t.id = mt.tag_id
  WHERE t.slug IN ('unofficial-retheme', 'manufacturer-retheme')
)
SELECT name FROM r
WHERE ftext LIKE '%licens%' OR ftext LIKE '%licence%' OR ftext LIKE '%official%'
   OR ftext LIKE '%permission%' OR ftext LIKE '%bootleg%'
   OR ftext LIKE '%authoriz%' OR ftext LIKE '%sanction%'
ORDER BY name;
```
