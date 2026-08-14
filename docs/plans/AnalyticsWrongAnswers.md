# Why the analytics layer returns confidently wrong answers

The recurring problem: an AI session needs information from the analytics foundation, writes a plausible query against `scripts/analysis/`, and gets a confidently wrong answer. This is not a complaint about difficulty — the queries are short and the domain is small. It is a complaint about a specific failure shape: **the wrong answer is syntactically valid, semantically plausible, numerically reasonable, and indistinguishable from a correct one.** Nothing errors.

## What is NOT the problem

The domain model is not complicated and the view layer is not bloated. `catalog.sql` is 1,419 lines of which 591 are comments: roughly 830 lines of SQL for 50 views, about 16 lines each. Of the layer's ~4,700 lines, ~45% is the self-test and mutation harness and ~25% is the claim-grain provenance and patch layers; the liveness-and-decode views that match the intuitive mental model are ~18%. Of nine documented instances of a wrong answer, one is attributable to genuine domain complexity (`model_edges` being outbound-only). The remainder are the mechanisms above.

## What IS the problem

The problems below are the distinct mechanisms that produce this.

### Absence has two spellings, chosen per column, and the column does not tell you which

Django stores an unset `CharField(blank=True)` as `''` and an unset nullable field as `NULL`. Both reach the views unchanged. In the same view, `models.year IS NULL` is the correct test for "no year" and `models.description IS NULL` is **always false** — 42 columns across 25 of the 68 public views carry `''` as their absent marker (swept with `UNPIVOT`/`SUM(CASE WHEN COLUMNS(*)::VARCHAR = '' ...)` over every public view). The natural query `SELECT count(*) FROM models WHERE description IS NULL` returns **0**; the true answer is **6,828**. `WHERE production_quantity > 1000` silently excludes the 5,462 models whose quantity is unrecorded, because the field is a text column whose empty state is `''`. Complicating any uniform rule: at least one `''` is a real value rather than an absence — `citation_root_domains.path_prefix` uses `''` to mean "whole host" and is compared as `= ''` in `provenance_checks.sql:253`.

### Identity values carry Django-internal encodings that the views pass through undecoded

`claims.subject_type` holds `catalog.person`, not `person`. `WHERE subject_type = 'person'` returns **0** rows against a true answer of **2,047**, and zero rows reads as a clean pass. The same class covers claim values stored as JSON where `"100"` and `100` are different values, and `status`, where `NULL` means active — `WHERE status = 'active'` matches **109** of **6,938** live models (1.6%) because 6,829 rows carry `NULL`. The views resolve `status` correctly and do not resolve the other two. There is no stated principle governing which encodings get normalized: `model_relationships.target_label` and `model_export_markets.target_market_label` are `NULLIF`'d at HEAD while every other `''` column is not, which appears to reflect who thought about it rather than a rule.

### Nothing detects a Django model field that no view exposes

`unexposed_entity` checks, exhaustively and structurally, that every first-class entity table has a view. There is no equivalent at field grain. `description` existed on nine taxonomy models and no view exposed it; the gap was found only because someone asked a question that needed it. `EDITING.md` states the consequence directly — a column absent from a view says nothing about the Django model, it means nobody promoted it — and records that this has already caused two sessions to report `Actor` and `ChangeSet` as concepts the system does not have. This is the mechanism that generated the coverage gap that started this investigation, and it is the only problem here whose fix would prevent recurrence rather than repair an instance.

### The query engine itself returned wrong aggregates

DuckDB's sqlite scanner (v1.5.5, extension `f79b1db`) collapses two branches of one query that aggregate over different attached SQLite tables when their pushed-down projection and filter are identical — which `WHERE status IS DISTINCT FROM 'deleted'` makes near-universal across the simple views. `sqlite_debug_show_queries` shows one scan issued for two branches. It affects `max` and `sum` as well as `count`; with three branches all three take the first's value; scalar subqueries, `OFFSET 0`, `threads=1` and `disabled_optimizers` do not avoid it. Two live instances were found: `foundation_summary` reported `game_formats` as **6** (`reward_types`' count) for a vocabulary holding **11** rows, and `_anchor_scan` reported `cabinets`, `display_types` and `technology_generations` as **11** live rows each. Both had been wrong for an unknown length of time with the self-test green throughout. This problem is a property of reading SQLite in place and is not fixable by anything written in the view layer.

### Dark detection's coverage is inversely correlated with its value

`anchor_dark` fires only at `live = 0` — total emptiness — so a join that breaks for half the rows passes silently. A total break on a well-populated column would be noticed by ordinary use; a total break on a sparse column would not, and the sparse columns are precisely the ones exempted (`technology_subgeneration_slug` and `display_subtype_slug` are both listed `sparse` in `_anchor_skip`). Its measure counts `''` as a live value, so a column that is 100% empty string reads as fully populated — meaning the detector has been blind to every blank-encoded column for the life of the layer, which is the intersection of this problem with the first one. It costs 7 checks, 12 mutations, 172 lines and 38 exemption entries, and 6 of those 7 checks exist only to police the exemption lists of the 1 check that does the work. It sweeps 695 columns; only 6 JSON extracts and 76 LEFT JOINs in the entire layer can go dark without a hard `Binder Error`.

### The mutation harness proves that checks fire, not that checks measure correctly

`check-mutations` breaks the catalog deliberately and asserts that the responsible check notices. It reported **131 mutations caught** while `_anchor_scan` was reporting one view's row counts for three others. That is not a harness failure — a check that fires on broken data can still be measuring the wrong thing — but it means the layer's strongest guarantee does not cover the failure class this document is about. Both defects found in this investigation were found by hand, by someone whose measurement contradicted an earlier measurement.

## Open questions

Whether the first two problems are one problem or two — both are Django encodings surviving into SQL, but they have different owners (the view layer can normalize `''`; whether the _database_ should stop storing it is a backend question). Whether the third problem is in scope for an analytics layer at all, or belongs with the model-driven metadata machinery that already exists for the frontend. Whether the fourth problem should be counted here, given it is an upstream defect rather than anything this project built. And whether the fifth and sixth are one observation — that this layer verifies structure thoroughly and verifies measurement not at all.
