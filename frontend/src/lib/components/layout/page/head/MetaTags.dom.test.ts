import { render } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { SITE_NAME } from '$lib/constants';

// Whatever host served the page, the emitted SEO tags must sit on
// PUBLIC_SITE_ORIGIN.
vi.mock('$env/dynamic/public', () => ({
  env: { PUBLIC_SITE_ORIGIN: 'https://flipcommons.org' },
}));
vi.mock('$app/environment', () => ({ building: false, browser: true, dev: false }));

const MetaTags = (await import('./MetaTags.svelte')).default;

function headAttr(selector: string, attr: string): string | null {
  return document.head.querySelector(selector)?.getAttribute(attr) ?? null;
}

describe('MetaTags site name', () => {
  // The site name is the short form everywhere Google reads it as a name —
  // here and in the WebSite JSON-LD node. The long SITE_TITLE belongs to tab
  // titles, which are not the site name.
  it('emits the short site name, not the tab-title form', () => {
    render(MetaTags, {
      props: {
        title: 'Circus',
        description: 'A pinball machine.',
        url: 'https://flipcommons.org/models/circus-11',
      },
    });
    expect(headAttr('meta[property="og:site_name"]', 'content')).toBe(SITE_NAME);
  });
});

describe('MetaTags on a non-public host', () => {
  const railwayUrl = 'https://flipcommons-production.up.railway.app/models/circus-11';

  it('pins the canonical to the public origin', () => {
    render(MetaTags, {
      props: { title: 'Circus', description: 'A pinball machine.', url: railwayUrl },
    });
    expect(headAttr('link[rel="canonical"]', 'href')).toBe(
      'https://flipcommons.org/models/circus-11',
    );
  });

  it('pins og:url to the public origin and keeps it equal to the canonical', () => {
    render(MetaTags, {
      props: { title: 'Circus', description: 'A pinball machine.', url: railwayUrl },
    });
    expect(headAttr('meta[property="og:url"]', 'content')).toBe(
      'https://flipcommons.org/models/circus-11',
    );
  });

  it('still strips query and hash from the canonical', () => {
    render(MetaTags, {
      props: {
        title: 'Circus',
        description: 'A pinball machine.',
        url: `${railwayUrl}?ref=twitter#top`,
      },
    });
    expect(headAttr('link[rel="canonical"]', 'href')).toBe(
      'https://flipcommons.org/models/circus-11',
    );
  });

  it('builds the fallback share image on the public origin', () => {
    render(MetaTags, {
      props: { title: 'Circus', description: 'A pinball machine.', url: railwayUrl },
    });
    const image = headAttr('meta[property="og:image"]', 'content');
    expect(image).not.toBeNull();
    expect(new URL(image!).origin).toBe('https://flipcommons.org');
  });
});
