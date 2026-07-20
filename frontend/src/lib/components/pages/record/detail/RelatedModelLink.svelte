<!-- @component The one renderer for a related model line — name link followed by a muted "(Maker · Year)" parenthetical, shown only when it disambiguates from the subject. A known maker links to its page; an unknown one (against a known subject) reads as "Unknown Manufacturer". Used by every lineage and relationship-edge section on both the mobile lists and the desktop sidebar. -->
<script lang="ts">
  import { resolve } from '$app/paths';
  import { UNKNOWN_MANUFACTURER_LABEL } from '$lib/entities/manufacturer';
  import type { ModelLineageLinkView } from '$lib/entities/model-lineage';

  let { link }: { link: ModelLineageLinkView } = $props();
</script>

<!-- Whitespace is hugged throughout: the component renders inline inside running
     prose (the export-edition sentence), where a stray leading or trailing space
     would show up as a gap before the comma. -->
<span class="related-model"
  ><a href={resolve('/models/[slug]', { slug: link.public_id })}>{link.name}</a
  >{#if link.manufacturer || link.year}&nbsp;<span class="muted"
      >({#if link.manufacturer?.kind === 'known'}<a
          class="maker"
          href={resolve('/manufacturers/[slug]', { slug: link.manufacturer.ref.public_id })}
          >{link.manufacturer.ref.name}</a
        >{:else if link.manufacturer?.kind === 'unknown'}{UNKNOWN_MANUFACTURER_LABEL}{/if}{#if link.manufacturer && link.year}&nbsp;·&nbsp;{/if}{#if link.year}{link.year}{/if})</span
    >{/if}</span
>

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
