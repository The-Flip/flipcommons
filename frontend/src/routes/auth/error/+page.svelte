<script lang="ts" module>
  // Auth-error codes mirror the backend `AuthErrorCode` Literal in
  // apps/accounts/api/auth_codes.py. Re-declared here (not derived from the
  // schema) because the callback view redirects with a query-string `reason`
  // rather than going through the typed Ninja API — there's no generated TS
  // shape to derive from. If the backend Literal changes, this list must move
  // in lockstep.
  type AuthErrorCode =
    | 'email_unverified'
    | 'account_conflict'
    | 'account_disabled'
    | 'state_invalid'
    | 'code_exchange_failed';

  type Cta = {
    label: string;
    href: string;
    // `/api/auth/login/` is a Django endpoint, not a SvelteKit route — the
    // router would 404 if it intercepted the click. `reload: true` opts the
    // link out of client-side routing. Home-exit CTAs (href `/`) point at a
    // real SvelteKit route, so client navigation is correct.
    reload: boolean;
  };

  type Content = {
    heading: string;
    body: string;
    cta: Cta;
  };

  // All CTAs are visually primary. The button is the only interactive element
  // on the page — treating "Back to home" as a secondary variant just makes
  // the page feel under-designed even though it's the only action available.
  const RETRY: Cta = {
    label: 'Try sign-in again',
    href: '/api/auth/login/',
    reload: true,
  };
  const HOME: Cta = {
    label: 'Back to home',
    href: '/',
    reload: false,
  };

  // Copy is final per .claude/plans/usernames-implementation.md. The two
  // operator-intervention cases deliberately offer no support-contact CTA —
  // this is a volunteer site with no support team, and a fake "Contact
  // support" link would be theater.
  const COPY: Record<AuthErrorCode, Content> = {
    email_unverified: {
      heading: 'Verify your email',
      body: 'Verify your email and try again.',
      cta: RETRY,
    },
    account_conflict: {
      heading: 'Account needs attention',
      body: 'Something about this account needs a human to sort out.',
      cta: HOME,
    },
    account_disabled: {
      heading: 'Account unavailable',
      body: "This account isn't currently active.",
      cta: HOME,
    },
    state_invalid: {
      heading: 'Sign-in expired',
      body: 'Your sign-in link expired.',
      cta: RETRY,
    },
    code_exchange_failed: {
      heading: 'Sign-in failed',
      body: "We couldn't complete sign-in.",
      cta: RETRY,
    },
  };

  const FALLBACK: Content = {
    heading: 'Something went wrong',
    body: 'An unexpected error occurred during sign-in.',
    cta: HOME,
  };

  function resolveAuthErrorContent(reason: string | null): Content {
    if (reason !== null && reason in COPY) return COPY[reason as AuthErrorCode];
    return FALLBACK;
  }
</script>

<script lang="ts">
  import { page } from '$app/state';
  import Button from '$lib/components/Button.svelte';
  import ErrorPage from '$lib/components/ErrorPage.svelte';

  const content = $derived(resolveAuthErrorContent(page.url.searchParams.get('reason')));
</script>

<ErrorPage heading={content.heading} body={content.body}>
  {#snippet cta()}
    <Button tag="a" href={content.cta.href} data-sveltekit-reload={content.cta.reload || undefined}>
      {content.cta.label}
    </Button>
  {/snippet}
</ErrorPage>
