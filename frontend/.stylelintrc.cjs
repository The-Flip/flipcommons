/**
 * Stylelint config — guards token discipline in component <style> blocks.
 *
 * Enforces:
 *   - @media queries use only the project's --breakpoint-* custom media
 *     (and prefers-color-scheme); raw min-width/max-width is rejected.
 *   - No raw hex / rgb / rgba / hsl / hsla colors in components — use the
 *     --color-* tokens defined in src/app.css.
 *   - No :global selectors (project rule; inline-disable is the escape hatch).
 *   - No !important.
 *
 * The `overrides` block at the bottom is a baseline: existing files with
 * pre-stylelint violations are listed there with the offending rules disabled.
 * Cleanup PRs remove entries from the list one file at a time. Analogous to
 * backend/mypy-baseline.txt.
 */

module.exports = {
  // Hand-picked rules only — we don't extend stylelint-config-standard
  // because it bundles stylistic preferences (hex shortening, modern
  // color notation, alpha %, descending-specificity, etc.) that this
  // project doesn't care about. Correctness rules from that config are
  // re-enabled below by name.
  plugins: ['stylelint-value-no-unknown-custom-properties'],
  // Flag inline /* stylelint-disable */ comments that no longer suppress
  // anything — keeps one-off exceptions honest as code drifts.
  reportNeedlessDisables: true,
  reportInvalidScopeDisables: true,
  rules: {
    // Catches typos like var(--colour-error) and references to tokens
    // that were never defined. importFrom points at app.css so all
    // declared --color-*, --shadow-*, --z-* tokens are recognized.
    // Component-local custom properties defined and consumed in the same
    // <style> block are also recognized automatically (the plugin sees
    // the whole stylesheet). Tokens set at runtime via parent style=""
    // props will need an override entry below at the consumer file.
    // If you ever introduce a globally-shared token defined only inside
    // some other component's <style> block (not app.css), the plugin
    // won't see it across files — define it in app.css or override.
    'csstools/value-no-unknown-custom-properties': [
      true,
      {
        importFrom: [
          'src/app.css',
          // Open Props provides --size-*, --font-size-*, --radius-*,
          // --ease-*, etc. which app.css consumes via @import (the plugin
          // doesn't follow @import, so we list the source explicitly).
          'node_modules/open-props/open-props.min.css',
        ],
      },
    ],
    // ---- Token discipline ----
    'color-no-hex': true,
    'function-disallowed-list': ['rgb', 'rgba', 'hsl', 'hsla'],
    'media-feature-name-allowed-list': [
      '--breakpoint-narrow',
      '--breakpoint-wide',
      'prefers-color-scheme',
    ],
    // z-index: must be a --z-* token for global stacking layers; plain
    // single-digit integers (0-9) are allowed for local stacking contexts
    // within a single component. Bans values like 10, 100, 1000 — those
    // are global layers and must be tokenized.
    'declaration-property-value-allowed-list': {
      'z-index': ['/^var\\(--z-/', '/^[0-9]$/', 'auto', 'inherit', 'initial', 'unset'],
    },
    // ---- Project rules ----
    'selector-pseudo-class-disallowed-list': ['global'],
    'declaration-no-important': true,
    // ---- Discipline (project-style) ----
    'color-named': 'never', // forces tokens; transparent/currentColor are exempt by default
    'selector-max-id': 0, // classes scale, IDs don't
    // ---- Free correctness wins (catch typos & malformed CSS) ----
    'property-no-unknown': true,
    'unit-no-unknown': true,
    'at-rule-no-unknown': [true, { ignoreAtRules: ['custom-media'] }],
    'function-no-unknown': true,
    'function-calc-no-unspaced-operator': true,
    'string-no-newline': true,
    'font-family-no-duplicate-names': true,
    'font-family-no-missing-generic-family-keyword': true,
    'keyframe-block-no-duplicate-selectors': true,
    'selector-anb-no-unmatchable': true,
    'selector-type-no-unknown': true,
    'selector-pseudo-class-no-unknown': true,
    'selector-pseudo-element-no-unknown': true,
    'media-query-no-invalid': true,
    'media-feature-name-value-no-unknown': true,
    'media-type-no-deprecated': true,
    'at-rule-descriptor-no-unknown': true,
    'at-rule-descriptor-value-no-unknown': true,
    'at-rule-prelude-no-invalid': true,
    'nesting-selector-no-missing-scoping-root': true,
    'no-invalid-double-slash-comments': true,
    'no-invalid-position-declaration': true,
    'no-irregular-whitespace': true,
    'annotation-no-unknown': true,
    'color-no-invalid-hex': true,
    'custom-property-no-missing-var-function': true,
    'declaration-block-no-duplicate-custom-properties': true,
    'declaration-property-value-no-unknown': true,
    'named-grid-areas-no-invalid': true,
    'syntax-string-no-invalid': true,
    // ---- Deprecated checks (warn about CSS that should migrate) ----
    'property-no-deprecated': true,
    'at-rule-no-deprecated': true,
    'declaration-property-value-keyword-no-deprecated': true,
    'declaration-block-no-duplicate-properties': true,
    'declaration-block-no-shorthand-property-overrides': true,
    'shorthand-property-no-redundant-values': true,
    'no-duplicate-selectors': true,
    'no-duplicate-at-import-rules': true,
    'no-invalid-position-at-import-rule': true,
    'no-unknown-animations': true,
    'block-no-empty': true,
    'comment-no-empty': true,
    'no-empty-source': null, // empty <style> blocks are fine in Svelte
  },
  overrides: [
    {
      files: ['**/*.svelte'],
      customSyntax: 'postcss-html',
    },
    // ---- Baseline ----
    // app.css and lib/themes/*.css define the design tokens; raw hex/rgba
    // inside :root[data-theme] blocks is the source of truth and exempt
    // from the no-color rules.
    {
      files: ['src/app.css', 'src/lib/themes/*.css'],
      rules: {
        'color-no-hex': null,
        'function-disallowed-list': null,
      },
    },
    // Components with deliberate :global usage (rendered HTML from
    // external sources). These are exceptions, not cleanup targets.
    {
      files: ['src/lib/components/Prose.svelte', 'src/lib/components/Markdown.svelte'],
      rules: {
        'selector-pseudo-class-disallowed-list': null,
        'selector-pseudo-class-no-unknown': null,
      },
    },
    // Components that consume custom properties set at runtime via Svelte
    // `style:--prop={value}` directives. The plugin only sees stylesheet
    // declarations, not runtime values, so these refs look "unknown."
    {
      files: ['src/lib/components/cards/Card.svelte'],
      rules: {
        'csstools/value-no-unknown-custom-properties': null,
      },
    },
    // Components whose decorative texture is built from many rgba black/
    // white gradient stops (shadow/highlight intensities, not themed
    // colors). Promoting these to tokens would add indirection without
    // enabling retheming. Intentional exception, not a cleanup target.
    {
      files: ['src/lib/components/effects/WearEffect.svelte'],
      rules: {
        'function-disallowed-list': null,
      },
    },
  ],
  ignoreFiles: ['build/**', '.svelte-kit/**', 'node_modules/**', 'src/lib/api/schema.d.ts'],
};
