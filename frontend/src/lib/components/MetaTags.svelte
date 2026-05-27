<script lang="ts">
  import { SITE_NAME } from '$lib/constants';
  import {
    buildFullTitle,
    truncateMetaDescription,
    truncateOgDescription,
    buildCanonicalUrl,
    twitterCardType,
  } from './meta-tags';

  let {
    title,
    description,
    url,
    image,
    imageAlt,
    ogType = 'article',
  }: {
    title: string;
    description: string;
    url: string;
    image?: string | null;
    imageAlt?: string;
    ogType?: 'website' | 'article' | 'profile';
  } = $props();

  let canonicalUrl = $derived(buildCanonicalUrl(url));
  let fullTitle = $derived(buildFullTitle(title));
  let metaDescription = $derived(truncateMetaDescription(description));
  let ogDescription = $derived(truncateOgDescription(description));
</script>

<svelte:head>
  <title>{fullTitle}</title>
  <meta name="description" content={metaDescription} />
  <link rel="canonical" href={canonicalUrl} />

  <meta property="og:type" content={ogType} />
  <meta property="og:site_name" content={SITE_NAME} />
  <meta property="og:title" content={title} />
  <meta property="og:description" content={ogDescription} />
  <meta property="og:url" content={canonicalUrl} />
  {#if image}
    <meta property="og:image" content={image} />
    {#if imageAlt}
      <meta property="og:image:alt" content={imageAlt} />
    {/if}
  {/if}

  <meta name="twitter:card" content={twitterCardType(image)} />
</svelte:head>
