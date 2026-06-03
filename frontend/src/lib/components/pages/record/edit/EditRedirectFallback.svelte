<!--
	Redirect fallback for manual URL trimming. Users who delete the section
	segment from /<entity>/<slug>/edit/<section> land at /<entity>/<slug>/edit,
	which otherwise has no UI of its own. This component forwards them to the
	platform-appropriate default section URL: `?edit=<default>` on desktop
	(modal editor over the detail page) or `/edit/<default>` on mobile
	(dedicated edit shell). Going straight to the final URL avoids a second
	`replaceState` hop on desktop.

	Consumed by each entity's /edit/+page.svelte. The companion +page.ts sets
	`ssr = false` so `createBelowBreakpointFlag` can return the browser's synchronous
	`matchMedia` value on first render — no loading state needed.
-->
<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { WIDE_BREAKPOINT } from '$lib/constants';
  import { createBelowBreakpointFlag } from '$lib/use-below-breakpoint.svelte';
  import { resolveHref } from '$lib/utils';

  let {
    basePath,
    defaultSegment,
    publicId,
  }: {
    basePath: string;
    defaultSegment: string;
    /** Override for entities whose route param isn't `slug` (e.g. Location's `[...path]`). */
    publicId?: string;
  } = $props();

  const isMobileFlag = createBelowBreakpointFlag(WIDE_BREAKPOINT);
  let isMobile = $derived<boolean | null>(isMobileFlag.current);

  $effect(() => {
    const id = publicId ?? page.params.slug;
    if (isMobile === false) {
      goto(resolveHref(`${basePath}/${id}?edit=${defaultSegment}`), { replaceState: true });
    }
    if (isMobile === true) {
      goto(resolveHref(`${basePath}/${id}/edit/${defaultSegment}`), { replaceState: true });
    }
  });
</script>
