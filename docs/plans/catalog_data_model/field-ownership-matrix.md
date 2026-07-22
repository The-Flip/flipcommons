# Field Ownership Matrix

Generated from runtime claims data (2026-03-16).

## Sources

| Source                 | Slug                  | Priority | Type      | Active Claims |
| ---------------------- | --------------------- | -------- | --------- | ------------- |
| this project Models    | `flipcommons-catalog` | 300      | editorial | 1,627         |
| this project Titles    | `flipcommons-catalog` | 300      | editorial | 683           |
| Editorial (Mfrs/Corps) | `editorial`           | 300      | editorial | 256           |
| OPDB                   | `opdb`                | 200      | database  | 25,998        |
| IPDB                   | `ipdb`                | 100      | database  | 102,146       |
| Flip Signs             | `flip-signs`          | 50       | editorial | 104           |

## MachineModel Fields

### Pinbase-canonical (owned by this project, move to Markdown files)

These fields are either already Pinbase-only or are relationship-shaping fields that must be owned by this project.

| Field              | Current Sources                                                        | Classification           | Notes                                                                    |
| ------------------ | ---------------------------------------------------------------------- | ------------------------ | ------------------------------------------------------------------------ |
| `name`             | flipcommons-catalog (388), ipdb (6,659), opdb (2,311), flip-signs (16) | **Pinbase-canonical**    | this project wins at priority 300; external claims remain for comparison |
| `title`            | flipcommons-catalog (388), ipdb (4,518), opdb (2,309)                  | **Relationship-shaping** | Must come from this project files; remove from OPDB/IPDB ingest          |
| `variant_of`       | flipcommons-catalog (87), opdb (116)                                   | **Relationship-shaping** | Must come from this project files; remove from OPDB ingest               |
| `converted_from`   | flipcommons-catalog (53)                                               | **Relationship-shaping** | Already Pinbase-only                                                     |
| `is_conversion`    | flipcommons-catalog (75)                                               | **Relationship-shaping** | Already Pinbase-only                                                     |
| `cabinet`          | flipcommons-catalog (30), opdb (30)                                    | **Pinbase-canonical**    | Move to this project files                                               |
| `display_type`     | flipcommons-catalog (1), opdb (2,115)                                  | **Pinbase-canonical**    | Move to this project files; keep OPDB for comparison                     |
| `description`      | flipcommons-catalog (1)                                                | **Pinbase-canonical**    | Move to Markdown body text                                               |
| `credit`           | ipdb (7,226)                                                           | **Relationship-shaping** | Must come from this project files; remove from IPDB ingest               |
| `theme`            | ipdb (8,543)                                                           | **Relationship-shaping** | Must come from this project files; remove from IPDB ingest               |
| `gameplay_feature` | ipdb (12,762)                                                          | **Relationship-shaping** | Must come from this project files; remove from IPDB ingest               |

### External comparison allowlist (keep ingesting from OPDB/IPDB)

These are non-relational factual fields. External sources continue to assert claims for comparison; this project files also assert them as canonical.

| Field                   | Current Sources                             | Notes                                       |
| ----------------------- | ------------------------------------------- | ------------------------------------------- |
| `name`                  | ipdb (6,659), opdb (2,311), flip-signs (16) | Comparison only; this project wins          |
| `manufacturer`          | ipdb (6,282), opdb (2,311), flip-signs (16) | Comparison only                             |
| `year`                  | ipdb (5,265), opdb (2,311), flip-signs (16) | Comparison only                             |
| `month`                 | ipdb (3,839), opdb (2,311), flip-signs (16) | Comparison only                             |
| `player_count`          | ipdb (6,531), opdb (2,115)                  | Comparison only                             |
| `technology_generation` | ipdb (6,506), opdb (2,115)                  | Comparison only                             |
| `display_type`          | opdb (2,115)                                | Comparison only                             |
| `system`                | ipdb (802)                                  | Comparison only                             |
| `cabinet`               | opdb (30)                                   | Comparison only                             |
| `ipdb_id`               | ipdb (6,659)                                | Cross-reference identity                    |
| `opdb_id`               | opdb (2,311)                                | Cross-reference identity                    |
| `ipdb_rating`           | ipdb (899)                                  | External rating; no this project equivalent |
| `production_quantity`   | ipdb (1,451), flip-signs (12)               | Comparison only                             |
| `abbreviation`          | opdb (493), ipdb (434)                      | Comparison only                             |

### External-only fields (keep as-is, not in this project files)

These fields exist only in external sources and are either raw evidence or metadata that this project does not need to own.

| Field                    | Source     | Claims | Notes                                      |
| ------------------------ | ---------- | ------ | ------------------------------------------ |
| `opdb.images`            | opdb       | 2,111  | Image media; separate ingest path          |
| `ipdb.image_urls`        | ipdb       | 5,532  | Image media; separate ingest path          |
| `opdb.description`       | opdb       | 6      | Raw OPDB prose; not this project editorial |
| `opdb.common_name`       | opdb       | 66     | OPDB-specific display name                 |
| `opdb.keywords`          | opdb       | 188    | Raw keyword buckets                        |
| `opdb.variant_features`  | opdb       | 751    | Raw variant feature strings                |
| `ipdb.notable_features`  | ipdb       | 5,209  | Raw feature text                           |
| `ipdb.notes`             | ipdb       | 5,060  | Raw notes                                  |
| `ipdb.toys`              | ipdb       | 294    | Raw toy lists                              |
| `ipdb.marketing_slogans` | ipdb       | 253    | Raw marketing text                         |
| `manufacturer_address`   | flip-signs | 15     | Flip-signs only; low value                 |

### Relationship-shaping denylist (remove from OPDB/IPDB ingest)

These fields must stop being asserted by external sources in the runtime claims pipeline:

- `title` — title grouping/membership
- `variant_of` — variant relationships
- `credit` — person/role credits
- `theme` — theme assignments
- `gameplay_feature` — gameplay feature assignments

After migration, these are asserted only by Pindata files.

## Title Fields

| Field          | Current Sources                                       | Classification                                             |
| -------------- | ----------------------------------------------------- | ---------------------------------------------------------- |
| `name`         | flipcommons-catalog (371), ipdb (4,518), opdb (1,702) | **Pinbase-canonical**; IPDB/OPDB remain for comparison     |
| `abbreviation` | flipcommons-catalog (138), opdb (326)                 | **Pinbase-canonical**; OPDB remains for comparison         |
| `franchise`    | flipcommons-catalog (174)                             | **Relationship-shaping**; already Pinbase-only             |
| `description`  | flip-signs (13)                                       | **Pinbase-canonical**; absorb sign copy into Markdown body |

## Manufacturer Fields

| Field         | Current Sources | Classification                              |
| ------------- | --------------- | ------------------------------------------- |
| `name`        | editorial (59)  | **Pinbase-canonical**; already Pinbase-only |
| `description` | editorial (30)  | **Pinbase-canonical**; already Pinbase-only |

Note: Fandom and Wikidata also assert manufacturer claims (founded/dissolved year, headquarters, description, logo, website) but these are enrichment sources handled by separate ingest commands that are unaffected by this migration.

## CorporateEntity Fields

| Field          | Current Sources | Classification                              |
| -------------- | --------------- | ------------------------------------------- |
| `name`         | editorial (90)  | **Pinbase-canonical**; already Pinbase-only |
| `years_active` | editorial (77)  | **Pinbase-canonical**; already Pinbase-only |

## Person Fields

| Field  | Current Sources                      | Classification                                                           |
| ------ | ------------------------------------ | ------------------------------------------------------------------------ |
| `name` | flipcommons-catalog (19), ipdb (583) | **Pinbase-canonical**; IPDB creates Person records during credit parsing |

Note: Fandom and Wikidata also assert person claims (bio, birth/death, birthplace) but these are enrichment sources handled by separate ingest commands.

## Taxonomy Fields

All taxonomy entities (Cabinet, CreditRole, DisplayType, DisplaySubtype, Franchise, GameFormat, GameplayFeature, Series, System, Tag, TechnologyGeneration, TechnologySubgeneration) are **Pinbase-only**. No external source asserts claims on these entities. They move to Markdown files with no comparison concerns.

## Summary

| Category                        | Fields                                                                                                                                                                | Action                                                         |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| Already Pinbase-only            | All taxonomy, converted_from, is_conversion, franchise, corporate entities                                                                                            | Move to Markdown; no ingest changes needed                     |
| Pinbase-canonical + comparison  | name, manufacturer, year, month, player_count, display_type, cabinet, technology_generation, system, abbreviation, ipdb_id, opdb_id, ipdb_rating, production_quantity | Move to Markdown; keep OPDB/IPDB claims for comparison         |
| Relationship-shaping (denylist) | title, variant_of, credit, theme, gameplay_feature                                                                                                                    | Move to Markdown; **remove** from OPDB/IPDB ingest             |
| External-only evidence          | opdb._, ipdb._, images, manufacturer_address                                                                                                                          | Keep as-is in external ingest; not in this project files       |
| Flip-signs retirement           | name, year, month, manufacturer, production_quantity, manufacturer_address, description                                                                               | Absorb descriptions into title Markdown; retire ingest command |
