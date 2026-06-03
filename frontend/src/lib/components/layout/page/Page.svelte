<script lang="ts">
  import type { Snippet } from 'svelte';

  type Width = 'narrow' | 'default' | 'wide' | 'extra-wide';

  let {
    width = 'default',
    children,
  }: {
    width?: Width;
    children: Snippet;
  } = $props();
</script>

<article class={width}>
  {@render children()}
</article>

<style>
  article {
    max-width: 48rem;
    /* Self-center inside whatever parent contains us. Required for focus-mode
       consumers (FocusSiteShell is full-width, so unconstrained otherwise);
       inside SiteShell's 72rem-centered main, the article now centers within
       that band instead of hugging the left edge. */
    margin: 0 auto;
  }

  article.narrow {
    /* Used by single-task focused pages (signup, auth-error). */
    max-width: 36rem;
  }

  article.wide {
    max-width: 56rem;
  }

  article.extra-wide {
    max-width: 64rem;
  }
</style>
