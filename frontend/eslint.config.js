import prettier from 'eslint-config-prettier';
import svelte from 'eslint-plugin-svelte';
import globals from 'globals';
import ts from 'typescript-eslint';

// Shared `no-restricted-imports` entries, referenced by the scoped blocks
// below. Flat config merges this rule by override — the LAST matching block
// wins and options are not unioned — so every block that needs a boundary must
// list it explicitly. Naming the entries keeps each message defined once.
//
// - NO_POSTHOG: posthog-js is the analytics vendor SDK. Only
//   src/lib/analytics/posthog.ts may touch it; everywhere else goes through the
//   $lib/analytics abstraction, keeping the vendor boundary one file wide so a
//   future swap is mechanical.
// - NO_API_INTERNAL: the createApiClient factory is an api/ implementation
//   detail. App code uses the default `client` ($lib/api/client) or
//   createServerClient ($lib/api/server); reaching into $lib/api/internal/ from
//   outside api/ is a layering bug.
const NO_POSTHOG = {
  name: 'posthog-js',
  message:
    "Don't import posthog-js directly — use the `analytics` export from $lib/analytics. Only src/lib/analytics/posthog.ts may touch the SDK.",
  allowTypeImports: true,
};
const NO_API_INTERNAL = {
  group: ['$lib/api/internal/*', '**/api/internal/*'],
  message:
    "Don't import from $lib/api/internal/ — use the default `client` from $lib/api/client or `createServerClient` from $lib/api/server.",
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
      ],
    },
  },
  {
    // Vendor boundaries, applied across src. The api/ and posthog.ts overrides
    // further down each relax one of these for their own files.
    files: SRC_FILES,
    rules: {
      'no-restricted-imports': ['error', { paths: [NO_POSTHOG], patterns: [NO_API_INTERNAL] }],
    },
  },
  {
    // Component-architecture boundary (see docs/plans/SvelteComponentReorg.md):
    // pages/ shells are page bodies — importable only from routes/ and from
    // within pages/. Scoped to everything except those, so any other module
    // reaching into a page shell is flagged. Precedes the api/ and posthog.ts
    // exemptions so those stay the final match for their own files.
    files: SRC_FILES,
    ignores: ['src/routes/**', 'src/lib/components/pages/**'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          paths: [NO_POSTHOG],
          patterns: [
            NO_API_INTERNAL,
            {
              group: ['$lib/components/pages/**'],
              message:
                'pages/ shells are page bodies — import them only from routes/ or from within pages/.',
            },
          ],
        },
      ],
    },
  },
  {
    // Component-architecture boundary: ui/ is primitives-only and domain-free.
    // It may compose other ui/ primitives but must not import any non-ui
    // component — dependency flows outward only. The `!…/ui` dir line is
    // required alongside `!…/ui/**`: gitignore semantics can't re-include
    // children while the parent dir stays excluded.
    files: ['src/lib/components/ui/**'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          paths: [NO_POSTHOG],
          patterns: [
            NO_API_INTERNAL,
            {
              group: ['$lib/components/**', '!$lib/components/ui', '!$lib/components/ui/**'],
              message:
                'ui/ is primitives-only — it may not import from any sibling components folder.',
            },
          ],
        },
      ],
    },
  },
  {
    // api/ may import its own internals (drops the api-internal boundary).
    files: ['src/lib/api/**'],
    rules: {
      'no-restricted-imports': ['error', { paths: [NO_POSTHOG] }],
    },
  },
  {
    // The PostHog adapter is the one file allowed to touch the SDK.
    files: ['src/lib/analytics/posthog.ts'],
    rules: {
      'no-restricted-imports': ['error', { patterns: [NO_API_INTERNAL] }],
    },
  },
  {
    ignores: ['build/', '.svelte-kit/', 'dist/', 'src/lib/api/schema.d.ts'],
  },
);
