<!-- @component The one renderer for a related model line — name link followed by a muted "(Maker · Year)" parenthetical (maker linked, shown only when it differs from the subject's). Used by every lineage and relationship-edge section on both the mobile lists and the desktop sidebar. -->
<script lang="ts">
  import { resolve } from '$app/paths';
  import type { ModelLineageLinkView } from '$lib/entities/model-lineage';

  let { link }: { link: ModelLineageLinkView } = $props();
</script>

<span class="related-model">
  <a href={resolve('/models/[slug]', { slug: link.public_id })}>{link.name}</a>
  {#if link.manufacturer || link.year}
    <span class="muted"
      >({#if link.manufacturer}<a
          class="maker"
          href={resolve('/manufacturers/[slug]', { slug: link.manufacturer.public_id })}
          >{link.manufacturer.name}</a
        >{/if}{#if link.manufacturer && link.year}&nbsp;·&nbsp;{/if}{#if link.year}{link.year}{/if})</span
    >
  {/if}
</span>

<style>
  .muted {
    color: var(--color-text-muted);
    font-size: var(--font-size-0);
  }

  /* Maker link reads as supplementary: link-colored but at the muted size. */
  .maker {
    font-size: var(--font-size-0);
  }
</style>
