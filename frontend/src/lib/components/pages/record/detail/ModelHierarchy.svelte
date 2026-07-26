<!-- @component Renders a title's machine models (variants nested under their parent) as `RelatedModelLink` lines — the model page's "Other Models In Title" and the title page's "Models" sidebar section. `subjectManufacturer`/`subjectYear` drive the shared disambiguation rule; when omitted, a value shared by every listed model is treated as the subject's (so only mixed lists show manufacturers/years). -->
<script lang="ts">
  import RelatedModelLink from './RelatedModelLink.svelte';
  import SidebarList from '$lib/components/layout/page/sidebar/SidebarList.svelte';
  import SidebarSection from '$lib/components/layout/page/sidebar/SidebarSection.svelte';
  import { titleModelsSubject, toModelLinkView } from '$lib/entities/model-lineage';
  import type { EntityRef } from '$lib/api/schema';

  interface Variant {
    name: string;
    public_id: string;
    year?: number | null;
  }

  interface Model {
    name: string;
    public_id: string;
    year?: number | null;
    manufacturer?: EntityRef | null;
    variants: Variant[];
  }

  let {
    models,
    heading = 'Models',
    excludeSlug = undefined,
    subjectManufacturer = undefined,
    subjectYear = undefined,
    inline = false,
  }: {
    models: Model[];
    heading?: string;
    excludeSlug?: string;
    subjectManufacturer?: string | null;
    subjectYear?: number | null;
    inline?: boolean;
  } = $props();

  function sortedVariants(variants: Variant[]): Variant[] {
    return [...variants].sort((a, b) => (a.year ?? 0) - (b.year ?? 0));
  }

  let filteredModels = $derived(
    excludeSlug ? models.filter((m) => m.public_id !== excludeSlug) : models,
  );

  let subject = $derived(
    titleModelsSubject(filteredModels, { manufacturer: subjectManufacturer, year: subjectYear }),
  );
</script>

{#snippet listItems()}
  {#each filteredModels as parent (parent.public_id)}
    <li>
      <RelatedModelLink link={toModelLinkView(parent, subject)} />
    </li>
    {#each sortedVariants(parent.variants) as variant (variant.public_id)}
      <li class="variant-indent">
        <!-- A variant is a cosmetic variation of its parent and shares its manufacturer,
             which this projection doesn't carry on the variant itself; inherit the
             parent's so an unknown manufacturer isn't inferred from the missing field. -->
        <RelatedModelLink
          link={toModelLinkView({ ...variant, manufacturer: parent.manufacturer }, subject)}
        />
      </li>
    {/each}
  {/each}
{/snippet}

{#if filteredModels.length > 0}
  {#if inline}
    <div class="relationship-group">
      <h3>{heading}</h3>
      <ul>
        {@render listItems()}
      </ul>
    </div>
  {:else}
    <SidebarSection {heading}>
      <SidebarList>
        {@render listItems()}
      </SidebarList>
    </SidebarSection>
  {/if}
{/if}

<style>
  .relationship-group {
    margin-bottom: var(--size-3);
  }

  .relationship-group:last-child {
    margin-bottom: 0;
  }

  .relationship-group h3 {
    font-size: var(--font-size-0);
    font-weight: 600;
    color: var(--color-text-muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin: 0 0 var(--size-1);
  }

  .relationship-group ul {
    list-style: none;
    padding: 0;
    margin: 0;
  }

  li {
    padding: var(--size-1) 0;
    font-size: var(--font-size-0);
  }

  li:not(:last-child):not(.variant-indent):not(:has(+ .variant-indent)) {
    border-bottom: 1px solid var(--color-border-soft);
  }

  .variant-indent {
    margin-left: var(--size-4);
  }

  .variant-indent::before {
    content: '└';
    margin-right: var(--size-2);
    color: var(--color-text-muted);
  }
</style>
