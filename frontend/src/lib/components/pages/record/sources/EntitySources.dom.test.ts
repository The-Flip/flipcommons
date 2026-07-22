import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import EntitySources from './EntitySources.test-harness.svelte';

const sampleClaim = {
  attribution: {
    author: { kind: 'source' as const, name: 'IPDB' },
    created_at: '2026-04-07T00:00:00Z',
  },
  field_name: 'year',
  claim_key: 'year',
  value: { raw: 1997 },
  is_winner: true,
  citations: [],
};

describe('EntitySources', () => {
  it('renders the field name, its value and the source backing it', () => {
    render(EntitySources, { props: { sources: [sampleClaim] } });

    expect(screen.getByRole('heading', { name: 'Sources', level: 1 })).toBeInTheDocument();
    expect(screen.getByText('year')).toBeInTheDocument();
    expect(screen.getByText('1997')).toBeInTheDocument();
    // Once as a contributor, once as the value's supporter.
    expect(screen.getAllByText('IPDB')).toHaveLength(2);
  });

  it('lists each contributor once, most recent first, linking usernames', () => {
    const older = {
      ...sampleClaim,
      claim_key: 'name',
      field_name: 'name',
      value: { raw: 'MM' },
    };
    const newest = {
      ...sampleClaim,
      attribution: {
        author: { kind: 'user' as const, username: 'editor' },
        created_at: '2026-05-01T00:00:00Z',
      },
    };

    render(EntitySources, { props: { sources: [older, sampleClaim, newest] } });

    const summary = screen.getByText(/Contributors to this record/);
    // Newest actor first, each listed once however many claims it made. The
    // separators are real text nodes, so the line copies as a sentence — CSS
    // generated content would render the same and copy as "editorIPDB".
    expect(summary.textContent?.trim()).toBe('Contributors to this record: editor, IPDB.');
    expect(summary.querySelector('a')).toHaveAttribute('href', '/users/editor');
  });

  it('renders a long scalar value verbatim (no string truncation)', () => {
    const long = 'a'.repeat(200);
    const longClaim = { ...sampleClaim, field_name: 'description', value: { raw: long } };
    render(EntitySources, { props: { sources: [longClaim] } });

    expect(screen.getByText(long)).toBeInTheDocument();
  });

  it('lists a claim citation once, numbered and linked to the citation list', () => {
    const cited = {
      ...sampleClaim,
      citations: [
        {
          source_name: 'Williams Flyer',
          source_type: 'web',
          author: '',
          year: 1993,
          locator: 'p. 2',
          quote: '',
          links: [
            { url: 'https://example.com/flyer', link_type: 'homepage', display_name: 'Scan' },
          ],
        },
      ],
    };
    const second = {
      ...cited,
      attribution: {
        author: { kind: 'source' as const, name: 'OPDB' },
        created_at: '2026-04-06T00:00:00Z',
      },
      is_winner: false,
    };

    render(EntitySources, { props: { sources: [cited, second] } });

    expect(screen.getByRole('link', { name: '[1]' })).toHaveAttribute('href', '#citation-1');
    expect(screen.getAllByText('Williams Flyer')).toHaveLength(1);
    expect(screen.getByRole('heading', { name: 'Citations', level: 2 })).toBeInTheDocument();
  });

  it('introduces the losing values with a lead-in, winner above it', () => {
    const displaced = {
      ...sampleClaim,
      value: { raw: 1998 },
      is_winner: false,
      attribution: {
        author: { kind: 'source' as const, name: 'OPDB' },
        created_at: '2026-04-06T00:00:00Z',
      },
    };

    render(EntitySources, { props: { sources: [sampleClaim, displaced] } });

    const leadIn = screen.getByText('Other values claimed:');
    expect(leadIn).toBeInTheDocument();
    // The winner precedes the lead-in; the displaced value follows it.
    expect(leadIn.compareDocumentPosition(screen.getByText('1997'))).toBe(
      Node.DOCUMENT_POSITION_PRECEDING,
    );
    expect(leadIn.compareDocumentPosition(screen.getByText('1998'))).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
  });

  it('omits the lead-in when a field has one value per related row', () => {
    const otherTheme = {
      ...sampleClaim,
      field_name: 'theme',
      claim_key: 'theme|theme:2',
      value: { raw: 'Fantasy' },
    };
    const theme = { ...otherTheme, claim_key: 'theme|theme:1', value: { raw: 'Medieval' } };

    render(EntitySources, { props: { sources: [theme, otherTheme] } });

    expect(screen.getByText('Medieval')).toBeInTheDocument();
    expect(screen.getByText('Fantasy')).toBeInTheDocument();
    expect(screen.queryByText('Other values claimed:')).not.toBeInTheDocument();
  });

  it('omits the citation list when no claim carries a citation', () => {
    render(EntitySources, { props: { sources: [sampleClaim] } });

    expect(screen.queryByRole('heading', { name: 'Citations' })).not.toBeInTheDocument();
  });

  it('renders the no-sources fallback when sources is empty', () => {
    render(EntitySources, { props: { sources: [] } });

    expect(screen.getByText(/no source data recorded yet/i)).toBeInTheDocument();
  });
});
