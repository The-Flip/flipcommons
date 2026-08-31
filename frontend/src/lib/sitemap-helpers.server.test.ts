import { describe, expect, it } from 'vitest';
import {
  escapeXmlText,
  ifNoneMatchSatisfied,
  renderSitemapIndex,
  renderUrlset,
  sitemapEtag,
  splitRouteAtParam,
  stripRouteGroups,
  urlElement,
} from './sitemap-helpers.server';

describe('stripRouteGroups', () => {
  it.each([
    ['/', '/'],
    ['/about', '/about'],
    ['/about/people', '/about/people'],
    ['/(legal)/privacy', '/privacy'],
    ['/(legal)/terms', '/terms'],
    ['/(legal)/licensing', '/licensing'],
    // Defends against a future nested-group shape — SvelteKit serves the
    // URL with every `/(group)` segment removed, so we must strip them all.
    ['/(outer)/(inner)/foo', '/foo'],
    // Group as the only segment: SvelteKit serves at `/`, not `''`.
    ['/(only)', '/'],
  ])('strips groups from %s → %s', (input, expected) => {
    expect(stripRouteGroups(input)).toBe(expected);
  });
});

describe('splitRouteAtParam', () => {
  it.each([
    ['/titles/[slug]', { prefix: '/titles/', suffix: '' }],
    ['/titles/[slug]/edit-history', { prefix: '/titles/', suffix: '/edit-history' }],
    ['/manufacturers/[slug]/systems', { prefix: '/manufacturers/', suffix: '/systems' }],
    ['/locations/[...path]', { prefix: '/locations/', suffix: '' }],
    ['/locations/[...path]/sources', { prefix: '/locations/', suffix: '/sources' }],
  ])('splits %s', (input, expected) => {
    expect(splitRouteAtParam(input)).toEqual(expected);
  });

  it('returns null for a route with no public-id segment', () => {
    expect(splitRouteAtParam('/about')).toBeNull();
    // A differently-named param is not a public-id slot — the route
    // convention is [slug] / [...path] only.
    expect(splitRouteAtParam('/users/[username]')).toBeNull();
  });

  it('returns null for a route with a second dynamic segment', () => {
    expect(splitRouteAtParam('/titles/[slug]/edit/[section]')).toBeNull();
  });
});

describe('escapeXmlText', () => {
  it('escapes the XML text-node metacharacters', () => {
    expect(escapeXmlText('a&b<c>d')).toBe('a&amp;b&lt;c&gt;d');
  });

  it('leaves URL-safe text untouched', () => {
    expect(escapeXmlText('https://flipcommons.org/titles/foo-bar')).toBe(
      'https://flipcommons.org/titles/foo-bar',
    );
  });
});

describe('renderUrlset', () => {
  it('wraps url elements in a urlset document', () => {
    const xml = renderUrlset([
      urlElement('https://flipcommons.org/', '2026-05-26'),
      urlElement('https://flipcommons.org/about', undefined),
    ]);
    expect(xml).toContain('<?xml version="1.0" encoding="UTF-8" ?>');
    expect(xml).toContain('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">');
    expect(xml).toMatch(
      /<loc>https:\/\/flipcommons\.org\/<\/loc>\s*<lastmod>2026-05-26<\/lastmod>/,
    );
    // No lastmod element for the entry without one.
    expect(xml).toMatch(/<loc>https:\/\/flipcommons\.org\/about<\/loc>\s*<\/url>/);
  });
});

describe('renderSitemapIndex', () => {
  it('lists exactly pageCount subpage locs', () => {
    const xml = renderSitemapIndex('https://flipcommons.org', 2);
    expect(xml).toContain('<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">');
    expect(xml).toContain('<loc>https://flipcommons.org/sitemap1.xml</loc>');
    expect(xml).toContain('<loc>https://flipcommons.org/sitemap2.xml</loc>');
    expect(xml).not.toContain('sitemap3.xml');
  });
});

describe('sitemapEtag', () => {
  it('is a quoted weak validator', () => {
    expect(sitemapEtag('<urlset/>')).toMatch(/^W\/"[\w-]+"$/);
  });

  it('is stable for identical bodies', () => {
    expect(sitemapEtag('<urlset/>')).toBe(sitemapEtag('<urlset/>'));
  });

  it('changes when a url is REMOVED, not just added', () => {
    const before = renderUrlset([
      urlElement('https://x.test/a', undefined),
      urlElement('https://x.test/b', undefined),
    ]);
    const after = renderUrlset([urlElement('https://x.test/a', undefined)]);
    expect(sitemapEtag(after)).not.toBe(sitemapEtag(before));
  });

  it('changes when only a lastmod moves', () => {
    const before = renderUrlset([urlElement('https://x.test/a', '2026-01-01')]);
    const after = renderUrlset([urlElement('https://x.test/a', '2026-01-02')]);
    expect(sitemapEtag(after)).not.toBe(sitemapEtag(before));
  });
});

describe('ifNoneMatchSatisfied', () => {
  const etag = 'W/"abc"';

  it.each([
    ['a missing header', null, false],
    ['an empty header', '', false],
    ['the identical tag', 'W/"abc"', true],
    ['the same tag sent strong (weak comparison)', '"abc"', true],
    ['a different tag', 'W/"xyz"', false],
    ['a list containing the tag', 'W/"xyz", W/"abc"', true],
    ['a list without the tag', 'W/"xyz", W/"def"', false],
    ['the wildcard', '*', true],
  ])('%s', (_label, header, expected) => {
    expect(ifNoneMatchSatisfied(header as string | null, etag)).toBe(expected);
  });
});
