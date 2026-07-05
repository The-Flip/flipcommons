import { describe, expect, it } from 'vitest';
import { citationLinkDisplay, type CitationLink } from './citation-links';

const link = (over: Partial<CitationLink> = {}): CitationLink => ({
  url: 'https://example.com',
  link_type: 'archive',
  display_name: 'Archive',
  ...over,
});

describe('citationLinkDisplay', () => {
  it('uses the reference link as the title href and drops it from the chips', () => {
    const reference = link({ url: 'https://ref.example', link_type: 'reference' });
    const archive = link({ url: 'https://archive.example', link_type: 'archive' });
    const result = citationLinkDisplay([reference, archive]);
    expect(result.titleHref).toBe('https://ref.example');
    expect(result.chips).toEqual([archive]);
  });

  it('leaves the title plain and shows every link as a chip when there is no reference', () => {
    const links = [
      link({ url: 'https://a.example', link_type: 'homepage' }),
      link({ url: 'https://b.example', link_type: 'publisher' }),
    ];
    const result = citationLinkDisplay(links);
    expect(result.titleHref).toBeUndefined();
    expect(result.chips).toEqual(links);
  });

  it('handles no links', () => {
    expect(citationLinkDisplay([])).toEqual({ titleHref: undefined, chips: [] });
  });
});
