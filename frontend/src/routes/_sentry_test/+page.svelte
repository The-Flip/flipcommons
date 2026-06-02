<script lang="ts">
  import { resolve } from '$app/paths';
  import Button from '$lib/components/Button.svelte';
  import Page from '$lib/components/Page.svelte';
  import { SITE_TITLE } from '$lib/constants';

  const ssrThrowHref = `${resolve('/_sentry_test')}?throw=ssr-load`;

  function throwInBrowser(): void {
    throw new Error('sentry_test: browser throw');
  }
</script>

<svelte:head>
  <title>Sentry test — {SITE_TITLE}</title>
</svelte:head>

<Page width="narrow">
  <h1>Sentry Test</h1>
  <p>
    Trigger on-demand exceptions to verify SSR-load and browser capture against the
    <code>flipcommons-frontend</code> Sentry project.
  </p>
  <div class="cta-row">
    <Button tag="a" href={ssrThrowHref} data-sveltekit-reload>Throw in SSR load</Button>
    <Button onclick={throwInBrowser}>Throw in browser</Button>
  </div>
</Page>

<style>
  .cta-row {
    display: flex;
    gap: var(--size-3);
    margin-top: var(--size-4);
  }
</style>
