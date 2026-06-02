<script lang="ts">
  import Breadcrumb, { type Crumb } from '$lib/components/Breadcrumb.svelte';

  let {
    name,
    heroImageUrl = null,
    heroImageAlt = '',
    parentLink = null,
    breadcrumbs = null,
    metaItems = [],
    aliases = [],
    aliasLabel = 'Also known as',
  }: {
    name: string;
    heroImageUrl?: string | null;
    heroImageAlt?: string;
    parentLink?: { text: string; href: string } | null;
    /**
     * When set, renders a breadcrumb trail in place of the kicker. Mutually
     * exclusive with `parentLink`.
     */
    breadcrumbs?: Crumb[] | null;
    metaItems?: Array<{ text: string; href?: string }>;
    aliases?: string[];
    aliasLabel?: string;
  } = $props();

  if (import.meta.env.DEV) {
    $effect(() => {
      if (parentLink && breadcrumbs) {
        console.warn(
          'HeroHeader: parentLink and breadcrumbs are mutually exclusive; breadcrumbs wins',
        );
      }
    });
  }
</script>

{#snippet content()}
  {#if breadcrumbs}
    <Breadcrumb crumbs={breadcrumbs} />
  {:else if parentLink}
    <a class="kicker" href={parentLink.href}>{parentLink.text}</a>
  {/if}
  <h1>{name}</h1>
  {#if aliases.length > 0}
    <p class="aliases">
      <span class="alias-label">{aliasLabel}:</span>
      {aliases.join(', ')}
    </p>
  {/if}
  {#if metaItems.length > 0}
    <div class="meta">
      {#each metaItems as item, i (i)}
        <span>
          {#if item.href}
            <a href={item.href}>{item.text}</a>
          {:else}
            {item.text}
          {/if}
        </span>
      {/each}
    </div>
  {/if}
{/snippet}

{#if heroImageUrl}
  <div class="hero-banner">
    <img class="hero-bg" src={heroImageUrl} alt={heroImageAlt} />
    <div class="hero-scrim"></div>
    <header class="hero-header">
      {@render content()}
    </header>
  </div>
{:else}
  <header>
    {@render content()}
  </header>
{/if}

<style>
  /* Kicker / parent link */
  .kicker {
    font-size: var(--font-size-1);
    font-weight: 500;
    color: var(--color-text-muted);
    text-decoration: none;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .kicker:hover {
    color: var(--color-link);
  }

  /* Heading */
  h1 {
    margin-bottom: var(--size-2);
  }

  /* Aliases */
  .aliases {
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
    margin: 0 0 var(--size-2);
  }

  .alias-label {
    font-weight: 600;
    color: var(--color-text);
    margin-right: var(--size-1);
  }

  /* Meta */
  .meta {
    display: flex;
    flex-wrap: wrap;
    gap: var(--size-2);
    font-size: var(--font-size-2);
    color: var(--color-text-muted);
  }

  .meta span:not(:last-child)::after {
    content: '·';
    margin-left: var(--size-2);
  }

  /* Plain header (no image) */
  header {
    margin-bottom: var(--size-2);
  }

  /* Hero banner with overlaid text */
  .hero-banner {
    position: relative;
    overflow: hidden;
    border-radius: var(--radius-3);
    min-height: 14rem;
    max-height: 22rem;
    margin-bottom: var(--size-5);
    display: flex;
    align-items: flex-end;
    background-color: var(--color-surface);
  }

  .hero-bg {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
    object-position: center 20%;
    z-index: 0;
  }

  .hero-scrim {
    position: absolute;
    inset: 0;
    z-index: 1;
    background: linear-gradient(
      to top,
      var(--color-scrim-strong) 0%,
      var(--color-scrim) 40%,
      transparent 100%
    );
    pointer-events: none;
  }

  .hero-header {
    position: relative;
    z-index: 2;
    padding: var(--size-5) var(--size-5) var(--size-4);
    width: 100%;
    margin-bottom: 0;
  }

  /* Hero overrides — light-on-dark text */
  .hero-header .kicker {
    color: var(--color-text-inverse-muted);
  }

  .hero-header .kicker:hover {
    color: var(--color-text-inverse);
  }

  .hero-header h1 {
    color: var(--color-text-inverse);
    text-shadow: 0 1px 4px var(--color-scrim-strong);
  }

  .hero-header .meta {
    color: var(--color-text-inverse-muted);
  }

  .hero-header .meta a {
    color: var(--color-text-inverse-muted);
    text-decoration: underline;
    text-decoration-color: color-mix(in srgb, var(--color-text-inverse) 40%, transparent);
  }

  .hero-header .meta a:hover {
    color: var(--color-text-inverse);
    text-decoration-color: var(--color-text-inverse);
  }

  .hero-header .meta span:not(:last-child)::after {
    color: color-mix(in srgb, var(--color-text-inverse) 50%, transparent);
  }

  /* Responsive */
  @media (--breakpoint-narrow) {
    .hero-banner {
      min-height: 10rem;
      max-height: 16rem;
      border-radius: 0;
      margin-left: calc(-1 * var(--size-5));
      margin-right: calc(-1 * var(--size-5));
    }

    .hero-header {
      padding: var(--size-3) var(--size-4) var(--size-3);
    }

    .hero-header h1 {
      font-size: var(--font-size-5);
    }

    .hero-header .meta {
      font-size: var(--font-size-0);
    }
  }
</style>
