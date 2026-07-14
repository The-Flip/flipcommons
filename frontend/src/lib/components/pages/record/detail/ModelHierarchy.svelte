<!-- @component Renders a title's machine models (variants nested under their parent) as `RelatedModelLink` lines — the model page's "Other Models In Title" and the title page's "Models" sidebar section. `subjectManufacturer`/`subjectYear` drive the shared disambiguation rule; when omitted, a value shared by every listed model is treated as the subject's (so only mixed lists show makers/years). -->
<script lang="ts">
  import RelatedModelLink from './RelatedModelLink.svelte';
  import SidebarList from '$lib/components/layout/page/sidebar/SidebarList.svelte';
  import SidebarSection from '$lib/components/layout/page/sidebar/SidebarSection.svelte';
  import { toModelLinkView, type RelatedModelSubject } from '$lib/entities/model-lineage';
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

  /** The value every listed model shares, or `null` when the list is mixed. */
  function unanimous<T>(values: (T | null)[]): T | null {
    const first = values[0] ?? null;
    return values.every((v) => (v ?? null) === first) ? first : null;
  }

  /**
   * The subject to suppress against: the caller's values when given, else the
   * unanimous value across the list (a maker or year every model shares is
   * effectively the title's own, so only mixed lists show them).
   */
  let subject = $derived.by((): RelatedModelSubject => ({
    manufacturer:
      subjectManufacturer !== undefined
        ? subjectManufacturer
        : unanimous(filteredModels.map((m) => m.manufacturer?.name ?? null)),
    year:
      subjectYear !== undefined
        ? subjectYear
        : unanimous(filteredModels.map((m) => m.year ?? null)),
  }));
</script>

{#snippet listItems()}
  {#each filteredModels as parent (parent.public_id)}
    <li>
      <RelatedModelLink link={toModelLinkView(parent, subject)} />
    </li>
    {#each sortedVariants(parent.variants) as variant (variant.public_id)}
      <li class="variant-indent">
        <RelatedModelLink link={toModelLinkView(variant, subject)} />
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
