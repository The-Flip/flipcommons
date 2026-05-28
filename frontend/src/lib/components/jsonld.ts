import { SITE_NAME } from '$lib/constants';
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
 * visible breadcrumb and the JSON-LD one.
 *
 * `pageUrl.pathname` already includes the base prefix, so callers reading
 * the *current* page's URL should use `pageUrl.origin + pageUrl.pathname`
 * directly rather than running pathname back through this helper.
 */
export function absolutize(pageUrl: URL, path: string): string {
  if (/^https?:\/\//.test(path)) return path;
  return pageUrl.origin + resolveHref(path);
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
      item: pageUrl.origin + pageUrl.pathname,
    },
  ];
  return { '@type': 'BreadcrumbList', itemListElement: items };
}

/**
 * Site-level WebSite node. No SearchAction — Google's sitelinks searchbox
 * requires SSR-rendered results at the target URL, but `/search` is CSR
 * (results render after hydration), so declaring a SearchAction would lie
 * to crawlers that don't execute JS.
 */
export function webSite(pageUrl: URL): JsonLdNode {
  const home = absolutize(pageUrl, '/');
  return {
    '@type': 'WebSite',
    '@id': home,
    name: SITE_NAME,
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
  const self = pageUrl.origin + pageUrl.pathname;
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
