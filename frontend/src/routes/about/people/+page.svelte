<script lang="ts">
  import { pageTitle } from '$lib/constants';
  import Breadcrumb from '$lib/components/Breadcrumb.svelte';
</script>

<svelte:head>
  <title>{pageTitle('People')}</title>
</svelte:head>

<Breadcrumb crumbs={[{ label: 'About', href: '/about' }]} current="People" />

<p class="lede">
  Flipcommons was started by two friends making something they wished existed, with care, curiosity,
  and fun.
</p>

<div class="people">
  <article class="person-card">
    <header>
      <img src="/about/people/moses.avif" alt="" loading="lazy" width="120" height="120" />
      <div class="ident">
        <h2>Dean Moses</h2>
        <p class="location">Berkeley, CA</p>
      </div>
    </header>
    <p>
      Moses has been making software since the web was born. A veteran of the early internet era in
      1990s San Francisco, he believes in the decentralized, community-built ideals that prevailed
      before the rise of giant platforms and feed algorithms.
    </p>
  </article>

  <article class="person-card">
    <header>
      <img src="/about/people/william.avif" alt="" loading="lazy" width="120" height="120" />
      <div class="ident">
        <h2>William Pietri</h2>
        <p class="location">Chicago, IL</p>
      </div>
    </header>
    <p>
      William is a software developer and founder of <a href="https://www.theflip.museum/"
        >The Flip</a
      >: Chicago's Playable Pinball Museum. He is a big Wikipedia fan and used to be a Wikipedia
      administrator. He's owned his Addams Family for 30 years, and has only gotten "dirty pool"
      once.
    </p>
  </article>
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
