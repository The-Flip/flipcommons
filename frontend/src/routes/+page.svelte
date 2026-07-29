<script lang="ts">
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import client from '$lib/api/client';
  import GameCard from '$lib/components/collections/cards/GameCard.svelte';
  import { SITE_TITLE } from '$lib/constants';
  import MetaTags from '$lib/components/layout/page/head/MetaTags.svelte';
  import JsonLd from '$lib/components/layout/page/head/JsonLd.svelte';
  import { jsonLdGraph, webSite } from '$lib/components/layout/page/head/jsonld';
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import type { ModelRecentSchema } from '$lib/api/schema';

  type RecentModel = ModelRecentSchema;

  let searchQuery = $state('');
  let recentModels = $state<RecentModel[]>([]);
  let titleCount = $state<number | null>(null);
  let manufacturerCount = $state<number | null>(null);
  let peopleCount = $state<number | null>(null);

  function fmt(n: number): string {
    return n.toLocaleString();
  }

  function handleSubmit(e: Event) {
    e.preventDefault();
    const q = searchQuery.trim();
    if (q) {
      goto(`${resolve('/search')}?q=${encodeURIComponent(q)}`);
    }
  }

  onMount(async () => {
    const [recentRes, statsRes] = await Promise.all([
      client.GET('/api/models/recent/'),
      client.GET('/api/stats'),
    ]);
    if (recentRes.data) recentModels = recentRes.data;
    if (statsRes.data) {
      titleCount = statsRes.data.titles;
      manufacturerCount = statsRes.data.manufacturers;
      peopleCount = statsRes.data.people;
    }
  });
</script>

<!-- No image prop: MetaTags falls back to the branded DEFAULT_SOCIAL_IMAGE,
     which is exactly the home page's intended share image. -->
<MetaTags
  title={SITE_TITLE}
  description="The encyclopedia of pinball machines, manufacturers, and the people who make them."
  url={page.url.href}
  ogType="website"
/>

<JsonLd data={jsonLdGraph([webSite(page.url)])} />

<div class="home">
  <header class="hero">
    <p class="hero-kicker">Welcome to the</p>
    <h1 class="hero-title">Flipcommons Pinball Encyclopedia</h1>
  </header>

  <form class="hero-search" onsubmit={handleSubmit}>
    <input
      type="search"
      placeholder="Search titles, manufacturers, people..."
      aria-label="Search the catalog"
      bind:value={searchQuery}
    />
  </form>

  <nav class="explore-links">
    <a href={resolve('/titles')} class="explore-card">
      <span class="explore-label">Titles</span>
      <span class="explore-desc"
        >{titleCount !== null ? fmt(titleCount) : 'Thousands of'} pinball machines from the 1930s to today</span
      >
    </a>
    <a href={resolve('/manufacturers')} class="explore-card">
      <span class="explore-label">Manufacturers</span>
      <span class="explore-desc"
        >{manufacturerCount !== null ? fmt(manufacturerCount) : 'Hundreds of'} companies from Gottlieb
        and Bally to Stern and Jersey Jack</span
      >
    </a>
    <a href={resolve('/people')} class="explore-card">
      <span class="explore-label">People</span>
      <span class="explore-desc"
        >{peopleCount !== null ? fmt(peopleCount) : 'Hundreds of'} designers, artists, and engineers behind
        the games</span
      >
    </a>
  </nav>

  {#if recentModels.length > 0}
    <section class="recent">
      <h2 class="recent-heading">Newest Machines</h2>
      <div class="recent-grid">
        {#each recentModels as model (model.slug)}
          <GameCard
            entityType="model"
            slug={model.slug}
            name={model.name}
            thumbnailUrl={model.thumbnail_url}
            manufacturerName={model.manufacturer_name}
            year={model.year}
          />
        {/each}
      </div>
    </section>
  {/if}
</div>

<style>
  .hero {
    text-align: center;
    margin-bottom: var(--size-6);
  }

  .hero-kicker {
    font-size: var(--font-size-2);
    color: var(--color-text-muted);
    margin: 0 0 var(--size-1);
  }

  .hero-title {
    margin: 0;
  }

  .hero-search {
    max-width: 36rem;
    margin: 0 auto var(--size-5);
  }

  .hero-search input[type='search'] {
    padding: var(--size-3) var(--size-4);
    font-size: var(--font-size-2);
    border-radius: var(--radius-3);
    transition:
      border-color 0.15s var(--ease-2),
      box-shadow 0.15s var(--ease-2);
  }

  .explore-links {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr));
    gap: var(--size-4);
    max-width: 54rem;
    margin: 0 auto;
  }

  .explore-card {
    display: flex;
    flex-direction: column;
    padding: var(--size-5);
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-2);
    text-decoration: none;
    transition:
      border-color 0.15s var(--ease-2),
      box-shadow 0.15s var(--ease-2);
  }

  .explore-card:hover {
    border-color: var(--color-link);
    box-shadow: var(--shadow-popover);
  }

  .explore-label {
    font-size: var(--font-size-4);
    font-weight: 600;
    color: var(--color-link);
    margin-bottom: var(--size-1);
  }

  .explore-desc {
    font-size: var(--font-size-1);
    color: var(--color-text-muted);
    line-height: 1.5;
  }

  .recent {
    max-width: 54rem;
    margin: var(--size-8) auto 0;
  }

  .recent-heading {
    font-size: var(--font-size-4);
    font-weight: 600;
    color: var(--color-text);
    margin-bottom: var(--size-4);
  }

  .recent-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: var(--size-4);
  }

  @media (--breakpoint-narrow) {
    .recent-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
