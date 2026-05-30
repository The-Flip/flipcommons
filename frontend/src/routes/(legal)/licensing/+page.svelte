<script lang="ts">
  import { page } from '$app/state';
  import { SITE_NAME } from '$lib/constants';
  import LastUpdated from '$lib/components/LastUpdated.svelte';
  import MetaTags from '$lib/components/MetaTags.svelte';
  import JsonLd from '$lib/components/JsonLd.svelte';
  import { jsonLdGraph, pageNode, breadcrumbList } from '$lib/components/jsonld';
  import { STATIC_LASTMOD, formatLastUpdated } from '$lib/static-lastmod';

  const title = 'Licensing';
  const description = `${SITE_NAME} licensing: how content and contributions are licensed for reuse.`;
</script>

<MetaTags {title} {description} url={page.url.href} ogType="website" />

<JsonLd
  data={jsonLdGraph([
    pageNode('WebPage', page.url, title, description),
    breadcrumbList(page.url, [{ label: 'Home', href: '/' }], title),
  ])}
/>

<h1>Licensing</h1>
<LastUpdated>Last updated: {formatLastUpdated(STATIC_LASTMOD['/(legal)/licensing'])}</LastUpdated>

<h2>Facts Are Free</h2>
<p>
  Facts — such as release dates, player counts, manufacturer names, and design credits — are not
  copyrightable. You are free to use the factual information in {SITE_NAME} for any purpose without restriction.
</p>

<h2>Text and Images Are Licensed Per-Source</h2>
<p>
  Descriptive text, images, and other creative content in {SITE_NAME} comes from multiple sources, each
  with its own license. The license for each piece of content is displayed alongside it in the UI and
  included in API responses.
</p>
<p>Common licenses you will encounter include:</p>
<ul>
  <li>
    <strong>Creative Commons Attribution (CC BY)</strong> — you may share and adapt the content, provided
    you give appropriate credit.
  </li>
  <li>
    <strong>Creative Commons Attribution-ShareAlike (CC BY-SA)</strong> — same as CC BY, but adaptations
    must be shared under the same or a compatible license.
  </li>
  <li>
    <strong>Public Domain / CC0</strong> — no restrictions. Use for any purpose.
  </li>
</ul>
<p>
  Always check the license shown with the specific content you want to use. When attribution is
  required, credit the original source as displayed.
</p>

<h2>API Data</h2>
<p>
  Data accessed through the {SITE_NAME} API carries the same licensing as the corresponding UI content.
  Each API response includes license and attribution metadata so you can comply with the applicable terms
  programmatically.
</p>
<p>
  See the <a href="/api-docs">API documentation</a> for details on response formats.
</p>

<h2>Questions</h2>
<p>
  If you have questions about licensing or data usage, email
  <a href="mailto:licensing@flipcommons.org">licensing@flipcommons.org</a>.
</p>
