import { describe, expect, test } from 'vitest';
import { jsonLdGraph, webSite, pageNode, breadcrumbList } from './jsonld';
import { SITE_NAME } from '$lib/constants';

const ORIGIN = 'https://flipcommons.org';

describe('jsonLdGraph', () => {
  test('wraps nodes in a schema.org @graph document', () => {
    expect(jsonLdGraph([{ '@type': 'WebPage', name: 'X' }])).toEqual({
      '@context': 'https://schema.org',
      '@graph': [{ '@type': 'WebPage', name: 'X' }],
    });
  });
});

describe('webSite', () => {
  test('emits a WebSite node anchored at the origin root', () => {
    expect(webSite(new URL(`${ORIGIN}/`))).toEqual({
      '@type': 'WebSite',
      '@id': `${ORIGIN}/`,
      name: SITE_NAME,
      url: `${ORIGIN}/`,
    });
  });

  test('derives root from non-root pageUrl', () => {
    const node = webSite(new URL(`${ORIGIN}/about/people`));
    expect(node['@id']).toBe(`${ORIGIN}/`);
    expect(node.url).toBe(`${ORIGIN}/`);
  });

  test('does NOT emit a SearchAction (search is CSR; would mislead crawlers)', () => {
    const node = webSite(new URL(`${ORIGIN}/`));
    expect(node).not.toHaveProperty('potentialAction');
  });
});

describe('pageNode', () => {
  test('emits a typed page node with @id/url derived from pageUrl', () => {
    expect(pageNode('WebPage', new URL(`${ORIGIN}/privacy`), 'Privacy Policy', 'desc')).toEqual({
      '@type': 'WebPage',
      '@id': `${ORIGIN}/privacy`,
      url: `${ORIGIN}/privacy`,
      name: 'Privacy Policy',
      description: 'desc',
      isPartOf: { '@id': `${ORIGIN}/` },
    });
  });

  test('strips query and hash from @id', () => {
    // pageNode reads pathname directly, so query/hash naturally don't appear.
    const node = pageNode('WebPage', new URL(`${ORIGIN}/privacy?x=1#top`), 'Privacy');
    expect(node['@id']).toBe(`${ORIGIN}/privacy`);
    expect(node.url).toBe(`${ORIGIN}/privacy`);
  });

  test('omits description when not provided', () => {
    const node = pageNode('AboutPage', new URL(`${ORIGIN}/about`), 'About');
    expect(node).not.toHaveProperty('description');
  });

  test('accepts CollectionPage and AboutPage types', () => {
    expect(pageNode('AboutPage', new URL(`${ORIGIN}/about`), 'About')['@type']).toBe('AboutPage');
    expect(pageNode('CollectionPage', new URL(`${ORIGIN}/about/people`), 'People')['@type']).toBe(
      'CollectionPage',
    );
  });
});

describe('breadcrumbList', () => {
  test('emits an itemListElement with sequential positions', () => {
    const node = breadcrumbList(
      new URL(`${ORIGIN}/about/people`),
      [
        { label: 'Home', href: '/' },
        { label: 'About', href: '/about' },
      ],
      'People',
    );
    expect(node).toEqual({
      '@type': 'BreadcrumbList',
      itemListElement: [
        { '@type': 'ListItem', position: 1, name: 'Home', item: `${ORIGIN}/` },
        { '@type': 'ListItem', position: 2, name: 'About', item: `${ORIGIN}/about` },
        { '@type': 'ListItem', position: 3, name: 'People', item: `${ORIGIN}/about/people` },
      ],
    });
  });

  test('absolutizes relative crumb hrefs against pageUrl origin', () => {
    const node = breadcrumbList(
      new URL(`${ORIGIN}/privacy`),
      [{ label: 'Home', href: '/' }],
      'Privacy',
    );
    const items = node.itemListElement as Array<{ item: string }>;
    expect(items[0].item).toBe(`${ORIGIN}/`);
    expect(items[1].item).toBe(`${ORIGIN}/privacy`);
  });

  test('leaves already-absolute crumb hrefs untouched', () => {
    const node = breadcrumbList(
      new URL(`${ORIGIN}/x`),
      [{ label: 'Ext', href: 'https://example.com/y' }],
      'X',
    );
    const items = node.itemListElement as Array<{ item: string }>;
    expect(items[0].item).toBe('https://example.com/y');
  });

  test('current item URL is derived from pageUrl pathname (drops query/hash)', () => {
    const node = breadcrumbList(
      new URL(`${ORIGIN}/privacy?ref=x#top`),
      [{ label: 'Home', href: '/' }],
      'Privacy',
    );
    const items = node.itemListElement as Array<{ item: string }>;
    expect(items[1].item).toBe(`${ORIGIN}/privacy`);
  });

  test('BreadcrumbList node has no @id (page-scoped, never referenced)', () => {
    const node = breadcrumbList(new URL(`${ORIGIN}/x`), [], 'X');
    expect(node).not.toHaveProperty('@id');
  });
});
