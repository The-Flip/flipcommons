import { describe, expect, it } from 'vitest';
import {
  escapeXmlText,
  renderSitemapIndex,
  renderUrlset,
  splitRouteAtParam,
  stripRouteGroups,
  urlElement,
} from './sitemap-helpers';

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
