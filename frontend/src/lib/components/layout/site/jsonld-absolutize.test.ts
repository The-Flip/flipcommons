import { describe, expect, test, vi } from 'vitest';

// Real SvelteKit `resolve()` returns paths RELATIVE to the current route
// (e.g. `../`, `./about`), not absolute ones — the identity mock used by the
// other jsonld tests hides that. Mimic the relative output here so absolutize
// is exercised the way it behaves under SSR.
vi.mock('$app/paths', () => ({
  resolve: (p: string) => {
    if (p === '/') return '../';
    return `..${p}`;
  },
}));

const { absolutize, breadcrumbList, webSite } = await import('./jsonld');

const PAGE = new URL('https://flipcommons.org/gameplay-features/10-bank-drop-targets');

describe('absolutize with relative resolve() output', () => {
  test('produces a clean absolute URL for an internal path', () => {
    expect(absolutize(PAGE, '/gameplay-features/10-bank-drop-targets')).toBe(
      'https://flipcommons.org/gameplay-features/10-bank-drop-targets',
    );
  });

  test('resolves the site root without a stray "../" segment', () => {
    expect(absolutize(PAGE, '/')).toBe('https://flipcommons.org/');
  });

  test('leaves already-absolute URLs untouched', () => {
    expect(absolutize(PAGE, 'https://example.com/y')).toBe('https://example.com/y');
  });
});

describe('helpers emit clean absolute URLs under relative resolve()', () => {
  test('breadcrumb Home item is the bare origin root', () => {
    const node = breadcrumbList(PAGE, [{ label: 'Home', href: '/' }], 'X');
    const items = node.itemListElement as Array<{ item: string }>;
    expect(items[0].item).toBe('https://flipcommons.org/');
  });

  test('webSite @id is the bare origin root', () => {
    expect(webSite(PAGE)['@id']).toBe('https://flipcommons.org/');
  });
});
