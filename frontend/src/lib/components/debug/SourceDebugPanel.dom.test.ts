import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import SourceDebugPanel from './SourceDebugPanel.svelte';

/** The panel opens expanded, so its body is already in the DOM. */
const body = () => screen.getByRole('region');

/** The preformatted value block belonging to the entry under *headingText*. */
function valueText(headingText: string): string {
  const heading = screen
    .getAllByRole('heading', { level: 3 })
    .find((h) => h.textContent?.includes(headingText));
  return heading?.closest('section')?.querySelector('pre')?.textContent ?? '';
}

describe('SourceDebugPanel', () => {
  it('renders nothing when nothing is parked', () => {
    // The API always sends extra_data, so an empty dict is the common case —
    // it must not produce a permanently empty accordion.
    const { container } = render(SourceDebugPanel, { extraData: {} });
    expect(container.textContent).toBe('');
  });

  it('renders nothing when every value is empty', () => {
    const { container } = render(SourceDebugPanel, {
      extraData: { 'ipdb.notes': '', 'opdb.keywords': [] },
    });
    expect(container.textContent).toBe('');
  });

  it('shows known sections under their labels, in declared order', () => {
    render(SourceDebugPanel, {
      extraData: {
        // Deliberately out of display order: the panel imposes its own.
        'opdb.keywords': ['tv', 'movie'],
        'ipdb.toys': 'Safe House toy.',
        'ipdb.notes': 'Fred Young did voice characterizations.',
      },
    });

    const headings = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent);
    expect(headings).toEqual(['IPDB notes', 'IPDB toys', 'OPDB keywords']);
  });

  it('joins string arrays into a comma-separated list', () => {
    render(SourceDebugPanel, { extraData: { 'opdb.keywords': ['tv', 'movie'] } });
    expect(screen.getByText('tv, movie')).toBeTruthy();
  });

  it('preserves raw source text verbatim rather than rendering it as markdown', () => {
    // Underscores and asterisks would become emphasis, and the CRLF pairs would
    // collapse, if this went through a markdown renderer. Vetting a patch against
    // source text needs the text exactly as the resolver parked it.
    const raw = 'Safe House toy: *army men*.\r\n\r\nSniper toy: _flips open_.';
    render(SourceDebugPanel, { extraData: { 'ipdb.toys': raw } });

    expect(body().querySelector('em')).toBeNull();
    expect(valueText('IPDB toys')).toBe(raw);
  });

  it('keeps single newlines intact', () => {
    render(SourceDebugPanel, { extraData: { 'ipdb.notes': 'Line one.\nLine two.' } });
    expect(valueText('IPDB notes')).toBe('Line one.\nLine two.');
  });

  it('hides suppressed keys and license stamps', () => {
    render(SourceDebugPanel, {
      extraData: {
        'ipdb.corporate_entity_name': 'Stern Pinball, Incorporated',
        'opdb.images': [{ urls: { medium: 'https://example.test/a.jpg' } }],
        'opdb.images.__license_id': 4,
        'opdb.images.__permissiveness_rank': 5,
      },
    });
    // All four are suppressed, so there is nothing to show and no accordion.
    // Notably this must not claim "no parked source data" — there is plenty,
    // it is just all hidden.
    expect(screen.queryByText(/Source Debug/)).toBeNull();
  });

  it('labels ipdb.model_number as the manufacturer id, not an IPDB one', () => {
    render(SourceDebugPanel, { extraData: { 'ipdb.model_number': '20021' } });

    const heading = screen.getByRole('heading', { level: 3 });
    expect(heading.textContent).toBe('Manufacturer Model ID');
    // Must not be mistaken for a key IPDB assigns, nor flagged as unrecognized.
    expect(heading.textContent).not.toContain('IPDB');
    expect(heading.textContent).not.toContain('unrecognized');
    expect(valueText('Manufacturer Model ID')).toBe('20021');
  });

  it('flags an unrecognized key as such, naming it', () => {
    render(SourceDebugPanel, { extraData: { theme: { theme: 429, exists: true } } });

    const heading = screen.getByRole('heading', { level: 3 });
    expect(heading.textContent).toContain('theme');
    expect(heading.textContent).toContain('unrecognized field');
    // The value is still shown — a developer needs to see what was parked.
    expect(valueText('theme')).toContain('429');
  });

  it('orders known sections before unrecognized ones', () => {
    render(SourceDebugPanel, {
      extraData: { theme: { exists: true }, 'ipdb.notes': 'A note.' },
    });

    const headings = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent);
    expect(headings[0]).toBe('IPDB notes');
    expect(headings[1]).toContain('theme');
  });
});
