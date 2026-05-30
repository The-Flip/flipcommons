import { SITE_NAME, SITE_TITLE } from '$lib/constants';

const MAX_META_DESC_LENGTH = 155;
const MAX_OG_DESC_LENGTH = 200;

export function buildFullTitle(title: string): string {
  return title === SITE_TITLE ? SITE_TITLE : `${title} — ${SITE_TITLE}`;
}

/**
 * Clean, untruncated meta description for an entity. Sources the backend's
 * plain-text projection (`description.plain` — markdown flattened, wikilink
 * tokens resolved to labels), **never** raw `.text` (which leaks `[[type:slug]]`
 * tokens into OG/Twitter/SERP descriptions). When the entity has no
 * description it uses `fallback` if given, else `"{name} — {SITE_NAME}"`.
 * Returns full prose: `MetaTags` owns the per-channel length budgets (155 for
 * `<meta>`, 200 for `og:`), so truncating here would starve the OG budget.
 */
export function metaDescriptionFor(
  profile: {
    name: string;
    description: { plain: string };
  },
  fallback?: string,
): string {
  return profile.description.plain || fallback || `${profile.name} — ${SITE_NAME}`;
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

/**
 * Branded fallback share image for pages with no entity image (manufacturers
 * without a logo, taxonomy terms, static pages, …). 1200×630 — the
 * `summary_large_image` aspect ratio. Used for both `og:image` and
 * `twitter:image`: in practice almost every previewer (Slack, Discord,
 * iMessage, LinkedIn, Facebook, Bluesky and X's own large card) renders
 * `og:image` and ignores Twitter's small-card mode, so a single landscape
 * asset previews cleanly everywhere and a square variant only risked being
 * cropped on the one surface that still honored it.
 */
export const DEFAULT_SOCIAL_IMAGE = {
  path: '/images/social_default.png',
  width: 1200,
  height: 630,
  type: 'image/png',
  alt: `${SITE_NAME} — the collaborative pinball encyclopedia`,
} as const;
