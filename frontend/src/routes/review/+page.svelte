<script lang="ts">
  import { resolve } from '$app/paths';
  import ClaimValue from '$lib/components/provenance/ClaimValue.svelte';
  import Page from '$lib/components/layout/page/Page.svelte';
  import PageHeader from '$lib/components/layout/page/PageHeader.svelte';
  import { pageTitle } from '$lib/constants';
  import { resolveHref } from '$lib/utils';

  let { data } = $props();
  let claims = $derived(data.claims);
</script>

<svelte:head>
  <title>{pageTitle('Claims Review')}</title>
</svelte:head>

<Page width="extra-wide">
  <PageHeader
    title="Claims Needing Review"
    subtitle={`${claims.length} claim${claims.length !== 1 ? 's' : ''} flagged for review`}
    --page-header-title-mb="var(--size-2)"
  />

  {#if claims.length === 0}
    <p class="empty">No claims need review.</p>
  {:else}
    <ul class="claim-list">
      {#each claims as claim (claim.id)}
        <li class="claim-card">
          <div class="claim-header">
            <span class="field-name"
              >{claim.field_name === 'group' ? 'title' : claim.field_name}</span
            >
            <span class="source">{claim.source_name}</span>
          </div>
          <div class="claim-value">
            <ClaimValue value={claim.value} />
          </div>
          <div class="claim-subject">
            <span class="label">Model:</span>
            {#if claim.subject_slug}
              <a href={resolve(`/models/${claim.subject_slug}`)}>{claim.subject_name}</a>
            {:else}
              {claim.subject_name}
            {/if}
          </div>
          {#if claim.title_slug}
            <div class="claim-subject">
              <span class="label">Title:</span>
              <a href={resolve(`/titles/${claim.title_slug}`)}>{claim.subject_name}</a>
            </div>
          {/if}
          <p class="claim-notes">{claim.needs_review_notes}</p>
          {#if claim.review_links.length > 0}
            <p class="claim-links">
              {#each claim.review_links as link, i (link.url)}
                {#if i > 0}
                  ·
                {/if}
                {#if link.url.startsWith('/')}
                  <a href={resolveHref(link.url)}>{link.label}</a>
                {:else}
                  <a href={link.url}>{link.label}</a>
                {/if}
              {/each}
            </p>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</Page>

<style>
  .empty {
    color: var(--color-text-muted);
    font-size: var(--font-size-2);
    padding: var(--size-8) 0;
    text-align: center;
  }

  .claim-list {
    list-style: none;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--size-3);
  }

  .claim-card {
    border: 1px solid var(--color-border);
    border-radius: var(--radius-2);
    padding: var(--size-3) var(--size-4);
  }

  .claim-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: var(--size-2);
  }

  .field-name {
    font-weight: 600;
    font-size: var(--font-size-0);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--color-warning-text);
  }

  .source {
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
  }

  .claim-value {
    font-size: var(--font-size-1);
    margin-bottom: var(--size-2);
    overflow-wrap: anywhere;
  }

  .claim-subject {
    font-size: var(--font-size-1);
    display: flex;
    align-items: baseline;
    gap: var(--size-2);
    margin-bottom: var(--size-1);
  }

  .label {
    font-size: var(--font-size-0);
    font-weight: 600;
    color: var(--color-text-muted);
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }

  .claim-notes {
    font-size: var(--font-size-1);
    color: var(--color-text-muted);
    line-height: var(--font-lineheight-3);
  }

  .claim-links {
    margin-top: var(--size-2);
    font-size: var(--font-size-0);
  }

  .claim-links a {
    color: var(--color-warning-text);
    text-decoration: underline;
  }
</style>
