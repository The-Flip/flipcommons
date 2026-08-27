import prettier from 'eslint-config-prettier';
import svelte from 'eslint-plugin-svelte';
import globals from 'globals';
import ts from 'typescript-eslint';

// Named `no-restricted-imports` entries, shared by the scoped blocks below.
// Flat config does not union this rule across overrides (the last matching block
// wins), so each block lists the entries it needs by name; defining each message
// once here keeps them consistent. The component-architecture boundaries
// (NO_PAGES / NO_SITE / NO_ROUTES) are documented in
// docs/plans/SvelteComponentReorg.md.

// posthog-js is the analytics vendor SDK. Only src/lib/analytics/posthog.ts may
// touch it; everywhere else goes through the $lib/analytics abstraction, keeping
// the vendor boundary one file wide so a future swap is mechanical.
const NO_POSTHOG = {
  name: 'posthog-js',
  message:
    "Don't import posthog-js directly — use the `analytics` export from $lib/analytics. Only src/lib/analytics/posthog.ts may touch the SDK.",
  allowTypeImports: true,
};
// The createApiClient factory is an api/ implementation detail. App code uses the
// default `client` ($lib/api/client) or createServerClient ($lib/api/server);
// reaching into $lib/api/internal/ from outside api/ is a layering bug.
const NO_API_INTERNAL = {
  group: ['$lib/api/internal/*', '**/api/internal/*'],
  message:
    "Don't import from $lib/api/internal/ — use the default `client` from $lib/api/client or `createServerClient` from $lib/api/server.",
};
// pages/ shells are page bodies — importable only from routes/ and from within
// pages/. Importing a page shell from a general component is a layering mistake.
const NO_PAGES = {
  group: ['$lib/components/pages/**'],
  message: 'pages/ shells are page bodies — import them only from routes/ or from within pages/.',
};
// layout/site/ holds the site-chrome shells (SiteShell etc.), wired into the app
// only by the root layout, so only routes/ may import them. The page-level layer
// components compose with is layout/page/ (Page, MetaTags, JsonLd, …) — not site/.
const NO_SITE = {
  group: ['$lib/components/layout/site/**'],
  message:
    'layout/site/ holds site-chrome shells — import them only from routes/ (they are wired in by the root layout). Page-level primitives live in layout/page/.',
};
// $lib must not depend on routes/: shared code belongs in $lib, single-route code
// stays route-private (routes/.../_components/). This is the boundary the
// route-private / switch-promotion conventions rely on. Relative specifiers are
// used because routes aren't $lib-addressable; test files are exempt (route-loader
// tests legitimately import `+layout.server`).
const NO_ROUTES = {
  group: ['**/routes/**'],
  message:
    '$lib must not import from routes/ — promote shared code into $lib, or keep single-route code route-private under routes/.../_components/. (Tests may import route loaders.)',
};
// ui/ is primitives-only and domain-free: it may compose other ui/ primitives
// but must not import any non-ui component. Dependency flows outward only. The
// `!…/ui` dir line is required alongside `!…/ui/**`: gitignore semantics can't
// re-include children while the parent dir stays excluded.
const NO_NON_UI = {
  group: ['$lib/components/**', '!$lib/components/ui', '!$lib/components/ui/**'],
  message: 'ui/ is primitives-only — it may not import from any sibling components folder.',
};
const SRC_FILES = [
  'src/**/*.ts',
  'src/**/*.js',
  'src/**/*.svelte',
  'src/**/*.svelte.ts',
  'src/**/*.svelte.js',
];

export default ts.config(
  ...ts.configs.recommended,
  ...svelte.configs.recommended,
  prettier,
  ...svelte.configs.prettier,
  {
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.node,
      },
    },
  },
  {
    files: ['**/*.svelte', '**/*.svelte.ts', '**/*.svelte.js'],
    languageOptions: {
      parserOptions: {
        parser: ts.parser,
      },
    },
  },
  {
    rules: {
      'svelte/no-navigation-without-resolve': 'off',
      // Standard convention: `_`-prefixed args/vars are intentionally unused.
      // Lets snippets accept required arguments they don't need to reference.
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
        },
      ],
      // Use named imports from `$lib/api/schema` instead of indexed access.
      // `openapi-typescript --root-types` emits top-level aliases for every
      // component schema, so `components['schemas']['Foo']` is always
      // expressible as `Foo`. Indexed access is allowed only in
      // `src/lib/api/client.ts` (the override below).
      // Type-position `components['schemas'][...]` parses as a
      // TSIndexedAccessType, not a MemberExpression — that's why this rule
      // targets the TS-specific node.
      'no-restricted-syntax': [
        'error',
        {
          selector:
            "TSIndexedAccessType[objectType.typeName.name='components'][indexType.literal.value='schemas']",
          message:
            "Use a named import from '$lib/api/schema' instead of components['schemas'][...].",
        },
        // Node writes console.warn to stderr alongside console.error, and
        // Railway classifies a plain-text stderr line as an error — so an SSR
        // console.warn is indistinguishable from a fault in the log explorer.
        // $lib/log emits JSON carrying its own level, which Railway reads
        // instead. Browser-only code gains nothing from the rule but loses
        // nothing either: the logger falls back to console off the server.
        {
          selector: "MemberExpression[object.name='console']",
          message:
            'Use `getLogger()` from $lib/log instead of console.* — a plain SSR console line is classified by its stream, so warnings read as errors in Railway.',
        },
      ],
    },
  },
  //
  // `no-restricted-imports` blocks below. Flat config does NOT union this rule
  // across overrides — the LAST matching block wins and silently drops earlier
  // options — so every block restates the full set it needs. Ordered so the
  // last block matching a file is its effective rule set:
  //
  //   1. base (all src) — vendor boundaries + no reaching into page/site shells
  //   2. routes/        — exempt from the shell rules (routes compose them)
  //   3. lib/           — adds the $lib → routes/ boundary
  //   4. pages/         — page shells may cross-import each other
  //   5. ui/            — primitives-only (subsumes the shell rules)
  //   6. api/           — may import its own internals
  //   7. posthog.ts     — the one file allowed the analytics SDK
  //   8. tests          — vendor boundaries only (the structural rules guard the
  //                       production graph; tests import across folders for setup)
  //
  {
    // Base for all src: vendor boundaries + no reaching into the page/site
    // shells. routes/ relaxes the shell rules below (it wires shells in).
    files: SRC_FILES,
    rules: {
      'no-restricted-imports': [
        'error',
        { paths: [NO_POSTHOG], patterns: [NO_API_INTERNAL, NO_SITE, NO_PAGES] },
      ],
    },
  },
  {
    // routes/ may import page shells and site shells — that's what routes are
    // for. Vendor boundaries still apply.
    files: ['src/routes/**'],
    rules: {
      'no-restricted-imports': ['error', { paths: [NO_POSTHOG], patterns: [NO_API_INTERNAL] }],
    },
  },
  {
    // lib/ adds the $lib → routes/ boundary on top of the base set.
    files: ['src/lib/**'],
    rules: {
      'no-restricted-imports': [
        'error',
        { paths: [NO_POSTHOG], patterns: [NO_API_INTERNAL, NO_SITE, NO_PAGES, NO_ROUTES] },
      ],
    },
  },
  {
    // pages/ shells import each other (across record/listing/error subfolders),
    // so drop NO_PAGES — but they must not import site shells or routes/.
    files: ['src/lib/components/pages/**'],
    rules: {
      'no-restricted-imports': [
        'error',
        { paths: [NO_POSTHOG], patterns: [NO_API_INTERNAL, NO_SITE, NO_ROUTES] },
      ],
    },
  },
  {
    // ui/ is primitives-only and domain-free: it may compose other ui/
    // primitives but no other component (NO_NON_UI subsumes the page/site
    // rules). Dependency flows outward only.
    files: ['src/lib/components/ui/**'],
    rules: {
      'no-restricted-imports': [
        'error',
        { paths: [NO_POSTHOG], patterns: [NO_API_INTERNAL, NO_NON_UI, NO_ROUTES] },
      ],
    },
  },
  {
    // api/ may import its own internals (drops NO_API_INTERNAL); still $lib, so
    // the routes/ boundary holds.
    files: ['src/lib/api/**'],
    rules: {
      'no-restricted-imports': ['error', { paths: [NO_POSTHOG], patterns: [NO_ROUTES] }],
    },
  },
  {
    // The PostHog adapter is the one file allowed to touch the SDK (drops
    // NO_POSTHOG); the api-internal and routes/ boundaries still hold.
    files: ['src/lib/analytics/posthog.ts'],
    rules: {
      'no-restricted-imports': ['error', { patterns: [NO_API_INTERNAL, NO_ROUTES] }],
    },
  },
  {
    // Test files: vendor boundaries only. The structural component boundaries
    // above guard the production dependency graph; tests don't ship and
    // legitimately import across folders for setup (route loaders, page shells,
    // fixtures). Last so it overrides the folder blocks for any test under them.
    files: ['src/**/*.test.ts', 'src/**/*.spec.ts'],
    rules: {
      'no-restricted-imports': ['error', { paths: [NO_POSTHOG], patterns: [NO_API_INTERNAL] }],
    },
  },
  {
    // One-off codemod scripts are CLI tools, not app code: they run under plain
    // node with a terminal attached, never on the SSR request path, so console
    // is their correct output channel and $lib is not importable from them.
    // (Dropping the whole rule also drops the schema selector, which is a
    // TS-only concern these .mjs files can't express anyway.)
    files: ['scripts/**'],
    rules: {
      'no-restricted-syntax': 'off',
    },
  },
  {
    ignores: ['build/', '.svelte-kit/', 'dist/', 'src/lib/api/schema.d.ts'],
  },
);
