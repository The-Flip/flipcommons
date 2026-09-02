import { SITE_NAME, SITE_TITLE } from '$lib/constants';
import { pageIdentity, publicUrl } from '$lib/public-url';
import { resolveHref } from '$lib/utils';

export type JsonLdNode = Record<string, unknown>;

export type Crumb = { label: string; href: string };

export function jsonLdGraph(nodes: JsonLdNode[]): Record<string, unknown> {
  return { '@context': 'https://schema.org', '@graph': nodes };
}

/**
 * Absolutize an internal path (or pass through an already-absolute URL).
 * Internal paths are routed through `resolveHref()` so any configured
 * `config.kit.paths.base` prefix is applied — matching what rendered <a>
 * hrefs look like and avoiding a base-vs-no-base mismatch between the
 * visible breadcrumb and the JSON-LD one. `resolveHref()` returns a path
 * relative to the current route (e.g. `../`), so it is resolved against
 * `publicUrl(pageUrl)` — same pathname, pinned to the public origin —
 * rather than concatenated onto an origin.
 *
 * `pageUrl.pathname` already includes the base prefix, so callers reading
 * the *current* page's URL should use `pageIdentity(pageUrl)` rather than
 * running pathname back through this helper.
 */
export function absolutize(pageUrl: URL, path: string): string {
  if (/^https?:\/\//.test(path)) return path;
  return new URL(resolveHref(path), publicUrl(pageUrl)).href;
}

/**
 * BreadcrumbList JSON-LD node. Emitted without `@id` — page-scoped, never
 * referenced from elsewhere.
 *
 * `crumbs` are the trail leading up to (but not including) the current page;
 * `currentLabel` is the label for the current page (its URL is taken from `pageUrl`).
 */
export function breadcrumbList(pageUrl: URL, crumbs: Crumb[], currentLabel: string): JsonLdNode {
  const items = [
    ...crumbs.map((c, i) => ({
      '@type': 'ListItem',
      position: i + 1,
      name: c.label,
      item: absolutize(pageUrl, c.href),
    })),
    {
      '@type': 'ListItem',
      position: crumbs.length + 1,
      name: currentLabel,
      item: pageIdentity(pageUrl),
    },
  ];
  return { '@type': 'BreadcrumbList', itemListElement: items };
}

/**
 * Site-level WebSite node. No SearchAction — Google's sitelinks searchbox
 * requires SSR-rendered results at the target URL, but `/search` is CSR
 * (results render after hydration), so declaring a SearchAction would lie
 * to crawlers that don't execute JS.
 *
 * This node is the strongest signal Google has for the site name it shows in
 * search results, and its guidance is to give a concise, commonly-recognized
 * name — long ones get truncated on narrow devices. So `name` is the short
 * form, matching `og:site_name`, the wordmark and the domain, and the long
 * form rides along as `alternateName`. The home page's `<title>` and `<h1>`
 * are free to carry the descriptive long form; Google reads them as
 * supporting signals, not as the name itself.
 */
export function webSite(pageUrl: URL): JsonLdNode {
  const home = absolutize(pageUrl, '/');
  return {
    '@type': 'WebSite',
    '@id': home,
    name: SITE_NAME,
    alternateName: SITE_TITLE,
    url: home,
  };
}

/**
 * Generic page node typed as the schema.org subtype that fits the page
 * (WebPage, AboutPage, CollectionPage). The page's `@id` and `url` are
 * derived from `pageUrl`.
 */
export function pageNode(
  type: 'WebPage' | 'AboutPage' | 'CollectionPage',
  pageUrl: URL,
  name: string,
  description?: string,
): JsonLdNode {
  const self = pageIdentity(pageUrl);
  const node: JsonLdNode = {
    '@type': type,
    '@id': self,
    url: self,
    name,
    isPartOf: { '@id': absolutize(pageUrl, '/') },
  };
  if (description) node.description = description;
  return node;
}
