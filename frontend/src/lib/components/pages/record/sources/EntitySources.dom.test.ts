import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import EntitySources from './EntitySources.test-harness.svelte';

/** A citation with no links or byline — enough to take a reference number. */
function bareCitation(id: number) {
  return {
    id,
    source_name: `Source ${id}`,
    source_type: 'web',
    author: '',
    year: null,
    locator: '',
    quote: '',
    links: [],
  };
}

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

  it('lists a claim citation once, its marker wired to the citation list', () => {
    const cited = {
      ...sampleClaim,
      citations: [
        {
          id: 7,
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

    // A link, because the marker navigates: the fragment jump works on its own
    // and the tooltip enhances it. It also carries the tooltip's identity.
    const marker = screen.getByRole('link', { name: 'Citation 1' });
    expect(marker).toHaveAttribute('href', '#citation-1');
    expect(marker).toHaveAttribute('data-cite-id', '7');
    expect(marker).toHaveAttribute('data-cite-index', '1');
    expect(screen.getAllByText('Williams Flyer')).toHaveLength(1);
    expect(screen.getByRole('heading', { name: 'Citations', level: 2 })).toBeInTheDocument();
    // The entry the marker's href resolves to.
    expect(document.querySelector('#citation-1')).toHaveAttribute('data-ref-index', '1');
    expect(screen.getByRole('button', { name: 'Back to citation 1' })).toBeInTheDocument();
  });

  it('does not turn a bracketed number in prose into a citation marker', () => {
    // The marker splitter treats any `[n]` as a marker, so a description that
    // merely mentions "[2]" must not resolve it against a number the value
    // only footnotes — that would assert a source the sentence never cited.
    const described = {
      ...sampleClaim,
      field_name: 'description',
      claim_key: 'description',
      value: {
        raw: 'Per the rulebook [2]. [[cite:id:7]]',
        display: { kind: 'markdown' as const, text: 'Per the rulebook [2]. [[cite:flyer]]' },
      },
      citations: [
        // Cited inline, so it takes number 1 and its marker sits in the text.
        { ...bareCitation(7), slug: 'flyer' },
        // Attached evidence on the same value, so it takes number 2 and
        // renders as a trailing footnote — the number the prose collides with.
        bareCitation(8),
      ],
    };

    const { container } = render(EntitySources, { props: { sources: [described] } });

    const descValue = [...container.querySelectorAll('.field')]
      .find((f) => f.querySelector('dt')?.textContent === 'description')!
      .querySelector('.value')!;

    // Exactly one marker for number 2: the footnote. The "[2]" the sentence
    // merely mentions stays text rather than becoming a second link to it.
    expect(descValue.querySelectorAll('a[data-cite-index="2"]')).toHaveLength(1);
    expect(descValue.querySelectorAll('a[data-cite-index]')).toHaveLength(2);
    expect(descValue.textContent).toContain('Per the rulebook [2].');
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

  it('renders a markdown value’s inline cite token as a numbered superscript', () => {
    const described = {
      ...sampleClaim,
      field_name: 'description',
      claim_key: 'description',
      value: {
        raw: 'Launched in 1966. [[cite:id:7]]',
        display: { kind: 'markdown' as const, text: 'Launched in 1966. [[cite:flyer-p2]]' },
      },
      citations: [
        {
          id: 7,
          source_name: 'Williams Flyer',
          source_type: 'web',
          author: '',
          year: 1993,
          locator: 'p. 2',
          quote: '',
          slug: 'flyer-p2',
          links: [],
        },
      ],
    };

    render(EntitySources, { props: { sources: [described] } });

    // The token is replaced in place, not shown raw and repeated as a footnote.
    expect(screen.getByText('Launched in 1966.', { exact: false })).toBeInTheDocument();
    expect(screen.queryByText(/\[\[cite:/)).not.toBeInTheDocument();
    // Exactly one marker: the inline one, wired the same way as a scalar
    // field's trailing marker rather than repeated as a footnote.
    const markers = screen.getAllByRole('link', { name: 'Citation 1' });
    expect(markers).toHaveLength(1);
    expect(markers[0]).toHaveAttribute('href', '#citation-1');
    expect(markers[0]).toHaveAttribute('data-cite-id', '7');
    expect(markers[0].closest('sup')).not.toBeNull();
  });

  it('collapses a prose value but leaves a scalar one alone', () => {
    const described = {
      ...sampleClaim,
      field_name: 'description',
      claim_key: 'description',
      value: {
        raw: 'Launched in 1966.',
        display: { kind: 'markdown' as const, text: 'Launched in 1966.' },
      },
    };

    const { container } = render(EntitySources, {
      props: { sources: [described, { ...sampleClaim }] },
    });

    // One collapsible, for the markdown value; `year` renders bare.
    expect(container.querySelectorAll('.collapsed')).toHaveLength(1);
  });

  it('opens the value holding a marker when its citation back-link is used', async () => {
    // The collapse clips a value's own markers, so a back-link that jumped
    // into a still-collapsed value would land on something invisible.
    const described = {
      ...sampleClaim,
      field_name: 'description',
      claim_key: 'description',
      value: {
        raw: 'Launched in 1966. [[cite:id:7]]',
        display: { kind: 'markdown' as const, text: 'Launched in 1966. [[cite:flyer-p2]]' },
      },
      citations: [
        {
          id: 7,
          source_name: 'Williams Flyer',
          source_type: 'web',
          author: '',
          year: 1993,
          locator: 'p. 2',
          quote: '',
          slug: 'flyer-p2',
          links: [],
        },
      ],
    };

    const { container } = render(EntitySources, { props: { sources: [described] } });
    expect(container.querySelectorAll('.collapsed')).toHaveLength(1);

    await fireEvent.click(screen.getByRole('button', { name: 'Back to citation 1' }));

    expect(container.querySelectorAll('.collapsed')).toHaveLength(0);
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
