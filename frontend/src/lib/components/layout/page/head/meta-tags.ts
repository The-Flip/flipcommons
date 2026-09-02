import { SITE_NAME, SITE_TITLE } from '$lib/constants';

const MAX_META_DESC_LENGTH = 155;
const MAX_OG_DESC_LENGTH = 200;

export function buildFullTitle(title: string): string {
  return title === SITE_TITLE ? SITE_TITLE : `${title} — ${SITE_TITLE}`;
}

/** Title labels for the sub-routes that need no further qualification, keyed by path segment. */
const SUBROUTE_LABELS: Record<string, string | undefined> = {
  'edit-history': 'Edit History',
  sources: 'Sources',
};

/** The part of an edit-section registry titling needs: a section's URL segment and its label. */
type TitledSection = { segment: string; label: string };

/**
 * Browser title for an entity page, qualified by the sub-route being viewed:
 * `"Earthshaker"`, `"Earthshaker • Sources"`, `"Earthshaker • Edit Name"`.
 *
 * `MetaTags` is rendered from the entity's `+layout.svelte`, which also wraps
 * `edit-history/`, `sources/` and `edit/[section]/`, so the sub-route has to
 * qualify the title itself or the whole sub-tree shares the bare entity name.
 *
 * `detailPath` is the entity's own detail route (`/models/earthshaker`,
 * `/locations/canada/on`) and the sub-route is whatever `pathname` adds beyond
 * it. Reading it relative to the entity rather than by segment position is what
 * keeps multi-segment location paths working, and what stops an entity whose
 * slug is `sources` from being read as its own sources page.
 *
 * `sections` is only consulted under `edit/`, to name the section being edited.
 */
export function entityPageTitle(
  name: string,
  pathname: string,
  detailPath: string,
  sections: readonly TitledSection[] = [],
): string {
  const label = subrouteLabel(pathname, detailPath, sections);
  return label ? `${name} • ${label}` : name;
}

function subrouteLabel(
  pathname: string,
  detailPath: string,
  sections: readonly TitledSection[],
): string | null {
  const base = stripTrailingSlash(detailPath);
  const path = stripTrailingSlash(pathname);
  if (!path.startsWith(`${base}/`)) return null;

  const [subroute, section] = path.slice(base.length + 1).split('/');
  if (subroute !== 'edit') return SUBROUTE_LABELS[subroute] ?? null;

  const sectionLabel = sections.find((s) => s.segment === section)?.label;
  return sectionLabel ? `Edit ${sectionLabel}` : 'Edit';
}

function stripTrailingSlash(path: string): string {
  return path.endsWith('/') ? path.slice(0, -1) : path;
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
