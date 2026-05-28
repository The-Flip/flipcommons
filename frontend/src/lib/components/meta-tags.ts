import { SITE_NAME, SITE_TITLE } from '$lib/constants';

const MAX_META_DESC_LENGTH = 155;
const MAX_OG_DESC_LENGTH = 200;

export function buildFullTitle(title: string): string {
  return title === SITE_TITLE ? SITE_TITLE : `${title} — ${SITE_TITLE}`;
}

/**
 * Clean, untruncated meta description for an entity. Sources the backend's
 * plain-text projection (`description.plain` — markdown flattened, wikilink
 * tokens resolved to labels), falling back to `"{name} — {SITE_NAME}"` when
 * the entity has no description. Returns full prose: `MetaTags` owns the
 * per-channel length budgets (155 for `<meta>`, 200 for `og:`), so truncating
 * here would starve the OG budget.
 */
export function metaDescriptionFor(profile: {
  name: string;
  description: { plain: string };
}): string {
  return profile.description.plain || `${profile.name} — ${SITE_NAME}`;
}

function truncate(text: string, max: number): string {
  return text.length > max ? text.slice(0, max - 1) + '…' : text;
}

/** ~155 chars — Google SERP display limit for <meta name="description">. */
export function truncateMetaDescription(description: string): string {
  return truncate(description, MAX_META_DESC_LENGTH);
}

/** ~200 chars — Facebook/LinkedIn preview cards for og:description. */
export function truncateOgDescription(description: string): string {
  return truncate(description, MAX_OG_DESC_LENGTH);
}

export function buildCanonicalUrl(url: string): string {
  return url.split('?')[0].split('#')[0];
}

export function twitterCardType(image: string | null | undefined): string {
  return image ? 'summary_large_image' : 'summary';
}
