<script lang="ts">
  import { resolve } from '$app/paths';
  import type { CreditSchema } from '$lib/api/schema';

  type Credit = CreditSchema;

  let { credits, showHeading = true }: { credits: Credit[]; showHeading?: boolean } = $props();

  let grouped = $derived.by(() => {
    const groups: { role: string; people: { name: string; slug: string }[] }[] = [];
    for (const c of credits) {
      const last = groups[groups.length - 1];
      if (last && last.role === c.role_display) {
        last.people.push({ name: c.person.name, slug: c.person.public_id });
      } else {
        groups.push({
          role: c.role_display,
          people: [{ name: c.person.name, slug: c.person.public_id }],
        });
      }
    }
    return groups;
  });
</script>

{#if credits.length > 0}
  <section class="credits">
    {#if showHeading}<h2>Credits</h2>{/if}
    <dl>
      {#each grouped as group (group.role)}
        <div class="credit-row">
          <dt>{group.role} by:</dt>
          <dd>
            {#each group.people as person, i (person.slug)}
              {#if i > 0},&nbsp;{/if}
              <a href={resolve(`/people/${person.slug}`)}>{person.name}</a>
            {/each}
          </dd>
        </div>
      {/each}
    </dl>
  </section>
{/if}

<style>
  h2 {
    font-size: var(--font-size-3);
    font-weight: 600;
    color: var(--color-text);
    margin-bottom: var(--size-3);
  }

  section {
    margin-bottom: var(--size-6);
  }

  dl {
    margin: 0;
  }

  .credit-row {
    display: flex;
    align-items: baseline;
    gap: var(--size-2);
    padding: var(--size-2) 0;
    border-bottom: 1px solid var(--color-border-soft);
    font-size: var(--font-size-1);
  }

  dt {
    color: var(--color-text-muted);
    font-size: var(--font-size-0);
    white-space: nowrap;
  }

  dd {
    margin: 0;
  }
</style>
