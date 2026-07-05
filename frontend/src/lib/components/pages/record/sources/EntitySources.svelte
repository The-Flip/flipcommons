<script lang="ts">
  import type { CitedChangeSetSchema, ClaimSchema } from '$lib/api/schema';
  import ClaimAttribution from '$lib/components/provenance/ClaimAttribution.svelte';
  import ClaimAuthor from '$lib/components/provenance/ClaimAuthor.svelte';
  import ClaimValue from '$lib/components/provenance/ClaimValue.svelte';
  import FocusContentShell from '$lib/components/layout/page/FocusContentShell.svelte';
  import { getEntityContext } from '$lib/entity-context';
  import { groupSourcesByField } from './entity-sources';
  import { displayLocator } from '$lib/citation-types';

  type Claim = ClaimSchema;
  type CitedChangeSet = CitedChangeSetSchema;

  let {
    sources,
    evidence = [],
  }: {
    sources: Claim[];
    evidence?: CitedChangeSet[];
  } = $props();

  let sourceGroups = $derived(groupSourcesByField(sources));
  const entity = getEntityContext();

  function claimAttribution(claim: Claim): string {
    const author = claim.attribution.author;
    return author.kind === 'source' ? author.name : author.username;
  }
</script>

{#snippet claimDetail(claim: Claim)}
  <ClaimAuthor attribution={claim.attribution} />
  <span class="claim-value-inline"><ClaimValue value={claim.value} /></span>
  {#if claim.is_winner}
    <span class="badge-used">used</span>
  {/if}
  {#if claim.changeset_note}
    <span class="claim-note">{claim.changeset_note}</span>
  {/if}
{/snippet}

<FocusContentShell
  backHref={entity.detailHref}
  recordName={entity.name}
  recordHref={entity.detailHref}
  maxWidth="64rem"
>
  {#snippet heading()}
    <h1 class="page-label">Sources</h1>
  {/snippet}

  {#if sources.length > 0}
    {@const { conflicts, agreed, single } = sourceGroups}
    {@const contributorNames = [
      ...new Set(sources.map(claimAttribution).filter((n) => n !== 'Unknown')),
    ]}
    <section class="sources">
      {#if evidence.length > 0}
        <section class="evidence">
          <h2>Evidence</h2>
          <ol class="changeset-list">
            {#each evidence as changeset (changeset.id)}
              <li class="changeset-card">
                <div class="changeset-header">
                  <ClaimAttribution attribution={changeset.attribution} />
                </div>
                {#if changeset.note}
                  <p class="evidence-note">{changeset.note}</p>
                {/if}
                <p class="changeset-fields">Applies to: {changeset.fields.join(', ')}</p>
                {#each changeset.citations as citation, i (i)}
                  <div class="evidence-citation">
                    <div class="source-name">{citation.source_name}</div>
                    {#if citation.author || citation.year}
                      <div class="meta">
                        {[citation.author, citation.year].filter(Boolean).join(', ')}
                      </div>
                    {/if}
                    {#if citation.locator}
                      <div class="locator">
                        {displayLocator(citation.source_type, citation.locator)}
                      </div>
                    {/if}
                    {#if citation.quote}
                      <blockquote class="quote">{citation.quote}</blockquote>
                    {/if}
                    {#if citation.links.length > 0}
                      <div class="links">
                        {#each citation.links as link (link.url)}
                          <a href={link.url} target="_blank" rel="noopener">{link.label}</a>
                        {/each}
                      </div>
                    {/if}
                  </div>
                {/each}
              </li>
            {/each}
          </ol>
        </section>
      {/if}

      <p class="sources-summary">
        {contributorNames.join(' and ')} contributed to this record.
      </p>

      {#if conflicts.length > 0}
        <details class="sources-group" open>
          <summary>
            <h3>
              Conflicts resolved ({conflicts.length} field{conflicts.length === 1 ? '' : 's'})
            </h3>
          </summary>
          <dl class="field-list">
            {#each conflicts as { field, claims } (field)}
              <div class="field-row conflict">
                <dt>{field}</dt>
                <dd>
                  {#each claims as claim, i (i)}
                    <span class="claim" class:used={claim.is_winner}>
                      {@render claimDetail(claim)}
                    </span>
                  {/each}
                </dd>
              </div>
            {/each}
          </dl>
        </details>
      {/if}

      {#if agreed.length > 0}
        <details class="sources-group">
          <summary>
            <h3>Sources agree ({agreed.length} field{agreed.length === 1 ? '' : 's'})</h3>
          </summary>
          <dl class="field-list">
            {#each agreed as { field, claims } (field)}
              <div class="field-row">
                <dt>{field}</dt>
                <dd>
                  <span class="claim used">
                    <span class="claim-value-inline"><ClaimValue value={claims[0].value} /></span>
                    <span class="source-list">
                      {#each claims as claim, i (i)}
                        {#if i > 0},
                        {/if}
                        <ClaimAuthor attribution={claim.attribution} />
                      {/each}
                    </span>
                  </span>
                </dd>
              </div>
            {/each}
          </dl>
        </details>
      {/if}

      {#if single.length > 0}
        <details class="sources-group">
          <summary>
            <h3>Single source ({single.length} field{single.length === 1 ? '' : 's'})</h3>
          </summary>
          <dl class="field-list">
            {#each single as { field, claims } (field)}
              <div class="field-row">
                <dt>{field}</dt>
                <dd>
                  <span class="claim used">
                    {@render claimDetail(claims[0])}
                  </span>
                </dd>
              </div>
            {/each}
          </dl>
        </details>
      {/if}
    </section>
  {:else}
    <p class="no-sources">No source data recorded yet.</p>
  {/if}
</FocusContentShell>

<style>
  .page-label {
    margin: 0;
    font-size: inherit;
    font-weight: inherit;
    color: inherit;
  }

  h2 {
    font-size: var(--font-size-3);
    font-weight: 600;
    color: var(--color-text);
    margin-bottom: var(--size-3);
  }

  .sources-summary {
    font-size: var(--font-size-1);
    color: var(--color-text-muted);
    margin-bottom: var(--size-4);
  }

  .evidence {
    margin-bottom: var(--size-5);
  }

  .changeset-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--size-3);
  }

  .changeset-card {
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-2);
    padding: var(--size-3);
    background: var(--color-surface);
  }

  .changeset-header {
    display: flex;
    align-items: center;
    gap: var(--size-2);
    margin-bottom: var(--size-2);
  }

  .evidence-note {
    margin: 0 0 var(--size-2);
    font-size: var(--font-size-00, 0.7rem);
    font-style: italic;
    color: var(--color-text-muted);
  }

  .sources-group {
    margin-bottom: var(--size-4);
  }

  .sources-group h3 {
    font-size: var(--font-size-1);
    font-weight: 600;
    color: var(--color-text);
    margin-bottom: var(--size-2);
  }

  .sources-group summary {
    cursor: pointer;
    list-style: revert;
  }

  .sources-group summary h3 {
    display: inline;
  }

  .field-list {
    display: grid;
    grid-template-columns: 1fr;
    gap: 0;
  }

  .field-row {
    display: flex;
    gap: var(--size-3);
    padding: var(--size-2) 0;
    border-bottom: 1px solid var(--color-border-soft);
    font-size: var(--font-size-0);
  }

  .field-row dt {
    min-width: 10rem;
    font-weight: 500;
    color: var(--color-text-muted);
    font-size: var(--font-size-0);
  }

  .field-row dd {
    display: flex;
    flex-direction: column;
    gap: var(--size-1);
    font-size: var(--font-size-0);
    color: var(--color-text);
    overflow-wrap: break-word;
  }

  .claim {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--size-2);
    opacity: 0.5;
  }

  .claim.used {
    opacity: 1;
  }

  .claim-value-inline {
    display: inline-block;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .badge-used {
    font-size: var(--font-size-00, 0.7rem);
    font-weight: 600;
    color: var(--color-link);
  }

  .claim-note {
    width: 100%;
    font-size: var(--font-size-00, 0.7rem);
    font-style: italic;
    color: var(--color-text-muted);
  }

  .changeset-fields {
    margin: 0 0 var(--size-2);
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
  }

  .evidence-citation {
    display: flex;
    flex-direction: column;
    gap: var(--size-1);
    padding-top: var(--size-2);
  }

  .quote {
    margin: 0;
    padding-left: var(--size-3);
    border-left: 2px solid var(--color-border-soft);
    font-size: var(--font-size-0);
    font-style: italic;
    color: var(--color-text-muted);
  }

  .links {
    display: flex;
    flex-wrap: wrap;
    gap: var(--size-2);
  }

  .links a {
    font-size: var(--font-size-0);
  }

  .source-list {
    font-size: var(--font-size-00, 0.7rem);
    color: var(--color-text-muted);
  }

  .no-sources {
    font-size: var(--font-size-1);
    color: var(--color-text-muted);
  }
</style>
