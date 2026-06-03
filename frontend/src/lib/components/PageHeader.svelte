<script lang="ts">
  import type { Snippet } from 'svelte';
  import Breadcrumb, { type Crumb } from './Breadcrumb.svelte';

  let {
    title,
    subtitle,
    breadcrumbs = null,
    children,
    actions,
  }: {
    title: string;
    subtitle?: string;
    breadcrumbs?: Crumb[] | null;
    children?: Snippet;
    actions?: Snippet;
  } = $props();
</script>

{#snippet body()}
  <h1>{title}</h1>
  {#if subtitle}
    <p class="subtitle">{subtitle}</p>
  {/if}
  {#if children}
    {@render children()}
  {/if}
{/snippet}

<header>
  {#if breadcrumbs}
    <Breadcrumb crumbs={breadcrumbs} />
  {/if}
  {#if actions}
    <div class="head-row">
      <div class="head-title">
        {@render body()}
      </div>
      <div class="head-actions">
        {@render actions()}
      </div>
    </div>
  {:else}
    {@render body()}
  {/if}
</header>

<style>
  header {
    margin-bottom: var(--page-header-mb, var(--size-6));
  }

  h1 {
    margin-bottom: var(--page-header-title-mb, var(--size-4));
  }

  .subtitle {
    font-size: var(--font-size-2);
    color: var(--color-text-muted);
    margin-top: var(--size-2);
  }

  .head-row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: var(--size-4);
  }

  .head-title {
    flex: 1;
    min-width: 0;
  }

  /* Only collapse the title margin when the h1 stands alone in the row
     (h1 + actions button). When a subtitle/description follows, keep the
     title↔body gap so it matches the plain (logged-out) layout. */
  .head-title h1:last-child {
    margin-bottom: 0;
  }

  .head-actions {
    flex-shrink: 0;
  }
</style>
