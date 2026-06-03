<script lang="ts">
  import client from '$lib/api/client';
  import { SITE_TITLE } from '$lib/constants';
  import type { SignupCheckResponseSchema } from '$lib/api/schema';
  import { classifySignupSubmit } from '$lib/signup-flow';
  import { USERNAME_MAX_LEN, USERNAME_MIN_LEN, checkUsernameFormat } from '$lib/username-format';
  import Button from '$lib/components/ui/Button.svelte';
  import Page from '$lib/components/layout/page/Page.svelte';

  // The full set of rejection reasons the server can surface (across /check
  // and /submit). Pulled from the generated schema rather than redeclared
  // locally so it stays in lockstep with the backend across `make codegen`.
  type ServerReason = NonNullable<SignupCheckResponseSchema['reason']>;

  type Status =
    | { kind: 'idle' }
    | { kind: 'checking' }
    | { kind: 'available' }
    | { kind: 'rejected'; reason: ServerReason };

  // Status-line copy. Pinned in the plan; if you tweak the strings, update
  // .claude/plans/usernames-implementation.md too so they stay in sync.
  const REASON_COPY: Record<ServerReason, string> = {
    too_short: 'Too short — must be at least 3 characters.',
    too_long: 'Too long — must be 20 characters or fewer.',
    bad_charset: 'Only lowercase letters, numbers, and hyphens allowed.',
    leading_or_trailing_hyphen: "Can't start or end with a hyphen.",
    consecutive_hyphens: "Can't have two hyphens in a row.",
    reserved: 'Not available.',
    taken: 'Not available',
  };

  let { data } = $props();

  let username = $state('');
  let status = $state<Status>({ kind: 'idle' });
  let submitting = $state(false);
  let submitError = $state<string | null>(null);
  let cancelling = $state(false);

  // Track the most recent check token so a stale in-flight response from a
  // prior keystroke doesn't overwrite the status for a newer query.
  let checkToken = 0;

  function normalize(value: string): string {
    // Lowercase as the user types; trim is reserved for paste/blur (see
    // handlers). Mid-keystroke trimming fights the user when they're typing
    // around a space they intend to remove themselves.
    return value.toLowerCase();
  }

  function onInput(event: Event & { currentTarget: HTMLInputElement }) {
    username = normalize(event.currentTarget.value);
    submitError = null;
  }

  function onPaste(event: ClipboardEvent) {
    // Trim on paste so a "  alice  " from the clipboard lands clean.
    const text = event.clipboardData?.getData('text');
    if (text === undefined) return;
    event.preventDefault();
    const input = event.currentTarget as HTMLInputElement;
    const start = input.selectionStart ?? username.length;
    const end = input.selectionEnd ?? username.length;
    const trimmed = text.trim();
    username = normalize(username.slice(0, start) + trimmed + username.slice(end));
  }

  function onBlur() {
    const trimmed = username.trim();
    if (trimmed !== username) username = trimmed;
  }

  // Debounced availability check. The pre-check via checkUsernameFormat gates
  // the network call so we don't burn /check rate-limit budget on input the
  // server is guaranteed to reject identically.
  $effect(() => {
    const value = username;
    // Bump the token on EVERY input change, before the early returns. A
    // /check response in flight for a prior value would otherwise still
    // match `checkToken` when the user shortened the input to below
    // MIN_LEN or made it format-invalid, promoting a stale "available"
    // verdict onto a now-invalid value.
    const token = ++checkToken;
    if (value.length < USERNAME_MIN_LEN) {
      // Suppress in-progress feedback: no message while the user is still
      // typing the first few characters. Submit will surface `too_short`
      // via the server's username_rejected response if they Continue early.
      status = { kind: 'idle' };
      return;
    }
    const localReason = checkUsernameFormat(value);
    if (localReason !== null) {
      status = { kind: 'rejected', reason: localReason };
      return;
    }
    status = { kind: 'checking' };
    const handle = setTimeout(() => {
      void runCheck(value, token);
    }, 250);
    return () => clearTimeout(handle);
  });

  async function runCheck(value: string, token: number) {
    try {
      const { data: body } = await client.GET('/api/auth/signup/check/', {
        params: { query: { username: value } },
      });
      if (token !== checkToken) return; // stale response
      if (!body) {
        // Network/auth/rate-limit error — leave status as "checking" was, but
        // surface nothing to the user. Submit-time will give them the real
        // answer. A noisy inline error here would be premature.
        status = { kind: 'idle' };
        return;
      }
      if (body.available) {
        status = { kind: 'available' };
      } else {
        // reason is null only on 200-available; not-available always carries one.
        status = { kind: 'rejected', reason: (body.reason ?? 'taken') as ServerReason };
      }
    } catch {
      if (token !== checkToken) return;
      status = { kind: 'idle' };
    }
  }

  async function onSubmit(event: Event) {
    event.preventDefault();
    if (submitting) return;
    submitting = true;
    submitError = null;
    try {
      const { data, response } = await client.POST('/api/auth/signup/', {
        body: { username },
      });
      const errorBody = data
        ? null
        : await response
            .clone()
            .json()
            .catch(() => null);
      const outcome = classifySignupSubmit(data, errorBody);
      switch (outcome.kind) {
        case 'success':
          window.location.href = outcome.redirect_url;
          return;
        case 'username_taken':
          status = { kind: 'rejected', reason: 'taken' };
          break;
        case 'username_rejected':
          status = { kind: 'rejected', reason: outcome.reason };
          break;
        case 'pending_invalid':
          window.location.href = '/login?next=/signup';
          return;
        case 'rate_limited':
          submitError = 'Too many attempts. Please wait a moment and try again.';
          break;
        case 'unknown_error':
          submitError = 'Something went wrong. Please try again.';
          break;
      }
    } catch {
      submitError = 'Network error. Please try again.';
    } finally {
      submitting = false;
    }
  }

  async function onCancel() {
    if (cancelling) return;
    cancelling = true;
    try {
      const { data: body } = await client.POST('/api/auth/signup/cancel/', {});
      // Even on error we want to send the user somewhere sane; the backend
      // always returns { logout_url } on 200, and 429 (the only other code)
      // means try again. Fall through to `/` rather than trapping them here.
      window.location.href = body?.logout_url ?? '/';
    } catch {
      window.location.href = '/';
    }
  }

  const submitDisabled = $derived(submitting || status.kind !== 'available' || username === '');

  const fullName = $derived(
    [data.pending.first_name, data.pending.last_name].filter(Boolean).join(' '),
  );
</script>

<svelte:head>
  <title>Pick your username — {SITE_TITLE}</title>
</svelte:head>

<Page width="narrow">
  <div class="signup-content">
    <header class="identity-bar">
      <span class="identity">
        Continuing as <strong>{fullName}</strong>
        <span class="separator" aria-hidden="true">•</span>
        <span class="email">{data.pending.email}</span>
      </span>
      <button type="button" class="not-you" onclick={onCancel} disabled={cancelling}>
        Not you?
      </button>
    </header>

    <section class="form-card">
      <h1>Pick your username</h1>
      <p class="hint">
        This is how you'll appear to the public. Lowercase letters, numbers, and hyphens — between {USERNAME_MIN_LEN}
        and {USERNAME_MAX_LEN} characters.
      </p>

      <form onsubmit={onSubmit}>
        <label class="field">
          <span class="visually-hidden">Username</span>
          <input
            type="text"
            name="username"
            autocomplete="off"
            autocapitalize="none"
            autocorrect="off"
            spellcheck="false"
            data-1p-ignore
            data-lpignore="true"
            data-bwignore
            data-form-type="other"
            maxlength={USERNAME_MAX_LEN}
            value={username}
            oninput={onInput}
            onpaste={onPaste}
            onblur={onBlur}
            aria-invalid={status.kind === 'rejected'}
            aria-describedby="status-line"
            placeholder="your-username"
          />
        </label>

        <p
          id="status-line"
          class="status"
          class:status-available={status.kind === 'available'}
          class:status-error={status.kind === 'rejected'}
          class:status-checking={status.kind === 'checking'}
          aria-live="polite"
        >
          {#if status.kind === 'checking'}
            Checking…
          {:else if status.kind === 'available'}
            Available
          {:else if status.kind === 'rejected'}
            {REASON_COPY[status.reason]}
          {:else}
            &nbsp;
          {/if}
        </p>

        {#if submitError}
          <p class="submit-error" role="alert">{submitError}</p>
        {/if}

        <Button type="submit" fullWidth disabled={submitDisabled}>
          {submitting ? 'Submitting…' : 'Continue'}
        </Button>
      </form>
    </section>
  </div>
</Page>

<style>
  .signup-content {
    /* Page handles max-width + centering; we own padding and the column
       gap between the identity bar and the form section. */
    padding: var(--size-6) var(--size-4);
    display: flex;
    flex-direction: column;
    gap: var(--size-6);
  }

  .identity-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--size-3);
    padding: var(--size-3) var(--size-4);
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-2);
    background: var(--color-surface, transparent);
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
  }

  .identity {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .identity strong {
    color: var(--color-text);
    font-weight: 600;
  }

  .separator {
    margin: 0 var(--size-2);
    color: var(--color-text-muted);
  }

  .not-you {
    background: none;
    border: none;
    padding: 0;
    color: var(--color-text-muted);
    text-decoration: underline;
    cursor: pointer;
    font: inherit;
    flex-shrink: 0;
  }

  .not-you:hover:not(:disabled) {
    color: var(--color-text);
  }

  .not-you:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .form-card {
    display: flex;
    flex-direction: column;
    gap: var(--size-4);
  }

  h1 {
    margin: 0;
    font-size: var(--font-size-3);
  }

  .hint {
    margin: 0;
    color: var(--color-text-muted);
    font-size: var(--font-size-0);
  }

  form {
    display: flex;
    flex-direction: column;
    gap: var(--size-3);
  }

  .field {
    display: block;
  }

  /* The global :where(input[type='text']) rule in app.css owns sizing,
     padding, border, background, etc. We only override the invalid-state
     border color so a rejected status reads as red. */
  input[aria-invalid='true'] {
    border-color: var(--color-error-border);
  }

  .status {
    margin: 0;
    min-height: 1.5em;
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
  }

  .status-available {
    color: var(--color-success-text);
  }

  .status-error {
    color: var(--color-error-text);
  }

  .status-checking {
    color: var(--color-text-muted);
    font-style: italic;
  }

  .submit-error {
    margin: 0;
    padding: var(--size-2) var(--size-3);
    background: var(--color-error-bg);
    border: 1px solid var(--color-error-border);
    color: var(--color-error-text);
    border-radius: var(--radius-2);
    font-size: var(--font-size-0);
  }

  .visually-hidden {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }
</style>
