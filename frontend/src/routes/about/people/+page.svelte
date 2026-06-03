<script lang="ts">
  import { page } from '$app/state';
  import { SITE_NAME } from '$lib/constants';
  import Breadcrumb from '$lib/components/layout/page/Breadcrumb.svelte';
  import MetaTags from '$lib/components/layout/site/MetaTags.svelte';
  import JsonLd from '$lib/components/layout/site/JsonLd.svelte';
  import { jsonLdGraph, pageNode, breadcrumbList } from '$lib/components/layout/site/jsonld';
  import { absoluteAssetUrl } from '$lib/utils';

  const title = 'People';
  const description = `The people behind ${SITE_NAME}: two friends building a pinball encyclopedia they wished existed.`;

  // Single source of truth for each team member; bio is hand-trusted HTML
  // (links only). JSON-LD strips tags for `description`.
  const team = [
    {
      name: 'Dean Moses',
      homeLocation: 'Berkeley, CA',
      image: '/about/people/moses.avif',
      bio: 'Moses has been making software since the web was born. A veteran of the early internet era in 1990s San Francisco, he believes in the decentralized, community-built ideals that prevailed before the rise of giant platforms and feed algorithms.',
    },
    {
      name: 'William Pietri',
      homeLocation: 'Chicago, IL',
      image: '/about/people/william.avif',
      bio: 'William is a software developer and founder of <a href="https://www.theflip.museum/">The Flip</a>: Chicago\'s Playable Pinball Museum. He is a big Wikipedia fan and used to be a Wikipedia administrator. He\'s owned his Addams Family for 30 years, and has only gotten "dirty pool" once.',
    },
  ];

  const stripTags = (html: string) => html.replace(/<[^>]+>/g, '');

  // Persons attach via `about` (Thing-typed), not `hasPart` (CreativeWork-typed) —
  // Person is a Thing but not a CreativeWork.
  const collection = {
    ...pageNode('CollectionPage', page.url, title, description),
    about: team.map((p) => ({
      '@type': 'Person',
      name: p.name,
      description: stripTags(p.bio),
      image: absoluteAssetUrl(p.image, page.url),
      homeLocation: { '@type': 'Place', name: p.homeLocation },
    })),
  };
</script>

<MetaTags {title} {description} url={page.url.href} />

<JsonLd
  data={jsonLdGraph([
    collection,
    breadcrumbList(
      page.url,
      [
        { label: 'Home', href: '/' },
        { label: 'About', href: '/about' },
      ],
      title,
    ),
  ])}
/>

<Breadcrumb crumbs={[{ label: 'About', href: '/about' }]} />

<p class="lede">
  Flipcommons was started by two friends making something they wished existed, with care, curiosity,
  and fun.
</p>

<div class="people">
  {#each team as p (p.name)}
    <article class="person-card">
      <header>
        <img src={p.image} alt="" loading="lazy" width="120" height="120" />
        <div class="ident">
          <h2>{p.name}</h2>
          <p class="location">{p.homeLocation}</p>
        </div>
      </header>
      <!-- eslint-disable-next-line svelte/no-at-html-tags -- bio is hand-authored static content in this file -->
      <p>{@html p.bio}</p>
    </article>
  {/each}
</div>

<figure class="both">
  <img
    src="/about/people/founders.avif"
    alt="Dean and William together"
    loading="lazy"
    width="900"
    height="1200"
  />
</figure>

<style>
  .lede {
    margin-top: var(--size-5);
  }

  .people {
    display: grid;
    grid-template-columns: 1fr;
    gap: var(--size-6);
    margin-top: var(--size-5);
  }

  @media (--breakpoint-wide) {
    .people {
      grid-template-columns: 1fr 1fr;
    }
  }

  .person-card {
    display: flex;
    flex-direction: column;
    gap: var(--size-3);
    padding: var(--size-4);
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-2);
    background: var(--color-surface);
  }

  .person-card header {
    display: flex;
    gap: var(--size-4);
    align-items: center;
  }

  .person-card img {
    flex-shrink: 0;
    width: 120px;
    height: 120px;
    object-fit: cover;
    border-radius: var(--radius-2);
    background: var(--color-surface);
  }

  .ident {
    display: flex;
    flex-direction: column;
    gap: var(--size-1);
  }

  .person-card h2 {
    font-size: var(--font-size-4);
    font-weight: 600;
    margin: 0;
  }

  .location {
    color: var(--color-text-muted);
    margin: 0;
  }

  .both {
    margin: var(--size-7) 0 0;
    text-align: center;
  }

  .both img {
    max-width: 100%;
    height: auto;
    border-radius: var(--radius-2);
  }
</style>
