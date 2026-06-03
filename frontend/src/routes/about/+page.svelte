<script lang="ts">
  import { page } from '$app/state';
  import { resolve } from '$app/paths';
  import { SITE_NAME } from '$lib/constants';
  import MetaTags from '$lib/components/layout/page/head/MetaTags.svelte';
  import JsonLd from '$lib/components/layout/page/head/JsonLd.svelte';
  import { jsonLdGraph, pageNode, breadcrumbList } from '$lib/components/layout/page/head/jsonld';
  import Prose from '$lib/components/ui/Prose.svelte';

  const title = 'About';
  const description = `About ${SITE_NAME} — a collaborative encyclopedia for pinball knowledge: the machines, the people, the manufacturers, the history.`;
</script>

<MetaTags {title} {description} url={page.url.href} />

<JsonLd
  data={jsonLdGraph([
    pageNode('AboutPage', page.url, title, description),
    breadcrumbList(page.url, [{ label: 'Home', href: '/' }], title),
  ])}
/>

<Prose>
  <h1>About {SITE_NAME}</h1>

  <p>
    {SITE_NAME} is a collaborative encyclopedia for pinball knowledge: the machines, the people behind
    each machine, the manufacturers, the history, the weird edge cases and the facts hiding in somebody's
    memory or basement binder.
  </p>

  <section>
    <h2>Why we're building it</h2>
    <p>
      Pinball has nearly a century of history spread across flyers, manuals, forums, collectors,
      museums, operators, designers and half-remembered stories. We want a collaborative,
      truth-seeking place where that knowledge can be collected, debated, corrected and made public.
    </p>
  </section>

  <section>
    <h2>Facts need footnotes</h2>
    <p>
      A lot of pinball facts come with asterisks. Who built what? Which company name counts? Was
      this a prototype, remake, conversion, export version? Instead of pretending every question has
      one simple answer, {SITE_NAME} is built on a system of claims, citations and sources, so disagreements
      can be seen, discussed and resolved without losing the history underneath.
    </p>
  </section>

  <section>
    <h2>Relationship to The Flip</h2>
    <p>
      This site grew out of work for <a href="https://www.theflip.museum/">The Flip</a>, Chicago's
      Playable Pinball Museum. Museums need good data to tell good stories. But this isn't only a
      museum catalog. It's meant to be useful to players, enthusiasts, researchers, contributors,
      collectors and anyone else who thinks pinball deserves better public memory.
    </p>
  </section>

  <section>
    <h2>Who started it</h2>
    <p>
      {SITE_NAME} was started by two friends building a thing we wished existed.
      <a href={resolve('/about/people')}>Meet the people</a> who got it going.
    </p>
  </section>

  <section>
    <h2>Get in touch</h2>
    <p>
      Say hi, share a correction, or tell us what's missing:
      <a href="mailto:howdy@flipcommons.org">howdy@flipcommons.org</a>.
    </p>
  </section>
</Prose>
