<!-- @component Cross-title lineage lines on the title page: "<model> is a bootleg of <other title>". One line per link — legacy lineage FKs and ModelRelationship edges alike. -->
<script lang="ts">
  import { resolve } from '$app/paths';
  import { relationshipSentence } from '$lib/entities/relationship-phrase';
  import type { CrossTitleLinkSchema } from '$lib/api/schema';

  let { relatedTitles }: { relatedTitles: CrossTitleLinkSchema[] } = $props();

  function label(link: CrossTitleLinkSchema): string {
    if (link.relation === 'remake_of') return 'is a remake of';
    return relationshipSentence(link.relation, link.license_status);
  }
</script>

<ul class="related-titles">
  {#each relatedTitles as link (`${link.source_model.public_id}-${link.relation}-${link.license_status}-${link.other_title.public_id}`)}
    <li>
      <span class="source">{link.source_model.name}</span>
      <span class="relation">{label(link)}</span>
      <a href={resolve(`/titles/${link.other_title.public_id}`)}>{link.other_title.name}</a>
    </li>
  {/each}
</ul>

<style>
  .related-titles {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--size-2);
  }

  .source {
    font-weight: 500;
  }

  .relation {
    color: var(--color-text-muted);
    margin: 0 var(--size-1);
  }
</style>
