import { describe, expect, it, vi } from 'vitest';

// Cross-host case for every SEO sink: with PUBLIC_SITE_ORIGIN configured and
// `page.url` on another host, each must emit the public origin. The
// canonical/og:url sink is covered by MetaTags.dom.test.ts.
vi.mock('$env/dynamic/public', () => ({
  env: { PUBLIC_SITE_ORIGIN: 'https://flipcommons.org' },
}));
vi.mock('$app/environment', () => ({ building: false, browser: false, dev: false }));

const { absolutize, breadcrumbList, pageNode } =
  await import('./components/layout/page/head/jsonld');
const { buildListingJsonLd } = await import('./entities/schema-org');
const { absoluteAssetUrl } = await import('./utils');

const RAILWAY = 'https://flipcommons-production.up.railway.app';
const PUBLIC = 'https://flipcommons.org';

describe('SEO sinks on a non-public host', () => {
  it('absolutize() rebases internal paths onto the public origin', () => {
    expect(absolutize(new URL(`${RAILWAY}/about/people`), '/about')).toBe(`${PUBLIC}/about`);
  });

  it('breadcrumbList() pins ancestor and current-page items to the public origin', () => {
    const node = breadcrumbList(
      new URL(`${RAILWAY}/about/people`),
      [{ label: 'About', href: '/about' }],
      'People',
    );
    const items = node.itemListElement as Array<{ item: string }>;
    expect(items.map((i) => i.item)).toEqual([`${PUBLIC}/about`, `${PUBLIC}/about/people`]);
  });

  it('pageNode() pins @id, url and isPartOf to the public origin', () => {
    const node = pageNode('WebPage', new URL(`${RAILWAY}/about`), 'About');
    expect(node['@id']).toBe(`${PUBLIC}/about`);
    expect(node.url).toBe(`${PUBLIC}/about`);
    expect(node.isPartOf).toEqual({ '@id': `${PUBLIC}/` });
  });

  it('buildListingJsonLd() pins the ItemList @id to the public origin', () => {
    const graph = buildListingJsonLd(
      'theme',
      [{ slug: 'fantasy', name: 'Fantasy' }],
      new URL(`${RAILWAY}/themes`),
    )['@graph'] as Record<string, unknown>[];
    const itemList = graph.find((n) => n['@type'] === 'ItemList');
    expect(itemList?.['@id']).toBe(`${PUBLIC}/themes#items`);
  });

  it('absoluteAssetUrl() resolves relative assets against the public origin', () => {
    expect(absoluteAssetUrl('/images/social_default.png', new URL(`${RAILWAY}/about`))).toBe(
      `${PUBLIC}/images/social_default.png`,
    );
  });
});
