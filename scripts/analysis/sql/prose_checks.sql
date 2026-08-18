-- Prose self-test — the invariants for prose.sql.
--
-- Not a standalone analysis: analytics.sql loads this after the layers, and
-- foundation_checks.sql folds `_prose_checks` into `foundation_checks`, so there is
-- ONE gate and one mutation-harness entry point. Private (`_` prefix) for that reason —
-- a public `*_checks` view would ALSO be discovered by the runner's sweep and every
-- failure would report twice. The same arrangement as provenance_checks.sql and
-- data_patches_checks.sql.
--
-- Same contract as the rest of the self-test: a row means something broke, empty means
-- healthy, and every check_name here needs a line in catalog_mutations.tsv proving it
-- fires. The house rule (IS DISTINCT FROM, never <>) is stated in full above
-- foundation_checks and applies here too.

CREATE OR REPLACE VIEW _prose_checks AS
  -- ─── The wikilink graph ────────────────────────────────────────────────────
  -- entity_prose has no check here: which entities owe a branch is MarkdownField
  -- membership, which SQL cannot see, and any SQL approximation would re-hardcode the
  -- field name the introspection exists to avoid. test_export_entity_registry asserts
  -- it against get_markdown_fields directly, which is the stronger guard.
  -- The source end of an edge always resolves. It is an inner join, so a row that
  -- cannot name its own source means the join stopped being one.
  SELECT 'reference_source_unresolved' AS check_name,
         source_entity_type || ':' || source_id::VARCHAR AS detail
  FROM record_references WHERE source_public_id IS NULL

  UNION ALL
  -- A target that entity_subjects HOLDS must decode. Membership is the guard: a
  -- GenericForeignKey has no on_delete, so an edge can outlive its target, and that
  -- dangling row is a catalog condition a broken-link rule should report — not a
  -- foundation failure that would take down every checked analysis with it.
  SELECT 'reference_target_undecoded',
         target_entity_type || ':' || target_id::VARCHAR
  FROM record_references r
  WHERE r.target_entity_type IS NOT NULL AND r.target_public_id IS NULL
    AND EXISTS (SELECT 1 FROM entity_subjects s
                WHERE s.subject_type = r.target_entity_type
                  AND s.subject_id = r.target_id)

  -- ─── Prose text ────────────────────────────────────────────────────────────
  -- prose_words is one row per authored prose field and nothing else. The tokenization
  -- itself is pinned by macro_prose_tokens against literals; what no literal can see is
  -- a JOIN added to the view, which fans the grain out silently — every consumer reads
  -- word POSITIONS off this array, so a duplicated row is a second coordinate system for
  -- the same text rather than a visibly wrong answer.
  UNION ALL
  SELECT 'prose_words_grain',
         'prose_words=' || (SELECT count(*) FROM prose_words)::VARCHAR
           || ' authored=' || (SELECT count(*) FROM entity_prose WHERE text IS NOT NULL)::VARCHAR
  WHERE (SELECT count(*) FROM prose_words)
        IS DISTINCT FROM (SELECT count(*) FROM entity_prose WHERE text IS NOT NULL);
