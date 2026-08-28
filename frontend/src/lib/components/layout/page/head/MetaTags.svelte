<script lang="ts">
  import { SITE_NAME } from '$lib/constants';
  import { publicUrl } from '$lib/public-url';
  import { absoluteAssetUrl } from '$lib/utils';
  import {
    buildFullTitle,
    truncateMetaDescription,
    truncateOgDescription,
    buildCanonicalUrl,
    DEFAULT_SOCIAL_IMAGE,
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

  let pageUrl = $derived(publicUrl(new URL(url)));
  let canonicalUrl = $derived(buildCanonicalUrl(pageUrl.href));
  let fullTitle = $derived(buildFullTitle(title));
  let metaDescription = $derived(truncateMetaDescription(description));
  let ogDescription = $derived(truncateOgDescription(description));

  // The shared image for OG and Twitter: the entity image when present, else a
  // branded 1200×630 default. Previewers overwhelmingly render og:image and
  // ignore Twitter's small-card mode, so one landscape asset covers every
  // surface; alt mirrors whichever image is used.
  let defaultSocialImageUrl = $derived(absoluteAssetUrl(DEFAULT_SOCIAL_IMAGE.path, pageUrl));
  let shareImageUrl = $derived(image ?? defaultSocialImageUrl);
  let shareImageAlt = $derived(image ? imageAlt : DEFAULT_SOCIAL_IMAGE.alt);
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
  {:else}
    <meta property="og:image" content={defaultSocialImageUrl} />
    <meta property="og:image:width" content={String(DEFAULT_SOCIAL_IMAGE.width)} />
    <meta property="og:image:height" content={String(DEFAULT_SOCIAL_IMAGE.height)} />
    <meta property="og:image:type" content={DEFAULT_SOCIAL_IMAGE.type} />
    <meta property="og:image:alt" content={DEFAULT_SOCIAL_IMAGE.alt} />
  {/if}

  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content={title} />
  <meta name="twitter:description" content={ogDescription} />
  <meta name="twitter:image" content={shareImageUrl} />
  {#if shareImageAlt}
    <meta name="twitter:image:alt" content={shareImageAlt} />
  {/if}
</svelte:head>
