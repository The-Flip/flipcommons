import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import CitationCreateStage from './CitationCreateStage.svelte';
import { CREATED_SOURCE } from './citation-fixtures';

const { mockPOST } = vi.hoisted(() => ({ mockPOST: vi.fn() }));
vi.mock('$lib/api/client', () => ({ default: { POST: mockPOST } }));

const BOOK_PARENT = {
  id: 30,
  name: 'Learning Python',
  source_type: 'book',
  author: 'Mark Lutz',
  identifier_key: '',
};

function noop() {}

beforeEach(() => mockPOST.mockReset());

describe('CitationCreateStage', () => {
  it('creates a parentless book root via the type picker (no URL field — web is URL-only)', async () => {
    const user = userEvent.setup();
    mockPOST.mockResolvedValueOnce({ data: CREATED_SOURCE });
    render(CitationCreateStage, {
      parentContext: null,
      seed: { kind: 'name', name: 'Pinball Compendium' },
      onsourcecreated: noop,
      oncancel: noop,
      onback: noop,
    });

    // Books and periodicals only — web sources are created by pasting a URL.
    expect(screen.getByRole('button', { name: 'Book' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Periodical' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'web' })).not.toBeInTheDocument();
    // No URL field anywhere in this stage.
    expect(screen.queryByLabelText('URL')).not.toBeInTheDocument();

    // A non-web source advances to the locator next, so the button says "Continue".
    await user.click(screen.getByRole('button', { name: /Continue/ }));

    await waitFor(() => expect(mockPOST).toHaveBeenCalled());
    expect(mockPOST).toHaveBeenCalledWith('/api/citation-sources/', {
      body: expect.objectContaining({
        name: 'Pinball Compendium',
        source_type: 'book',
        parent_id: null,
      }),
    });
  });

  it('creates an edition under a parent (type locked, linkless)', async () => {
    const user = userEvent.setup();
    mockPOST.mockResolvedValueOnce({ data: CREATED_SOURCE });
    render(CitationCreateStage, {
      parentContext: BOOK_PARENT,
      seed: { kind: 'name', name: 'Second Edition' },
      onsourcecreated: noop,
      oncancel: noop,
      onback: noop,
    });

    // A parent locks the type, so no picker.
    expect(screen.queryByRole('button', { name: 'Book' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Continue/ }));

    await waitFor(() => expect(mockPOST).toHaveBeenCalled());
    expect(mockPOST).toHaveBeenCalledWith('/api/citation-sources/', {
      body: expect.objectContaining({
        source_type: 'book',
        parent_id: BOOK_PARENT.id,
      }),
    });
  });

  it('creates a movie via the video chip, with Year prompted', async () => {
    const user = userEvent.setup();
    mockPOST.mockResolvedValueOnce({ data: CREATED_SOURCE });
    render(CitationCreateStage, {
      parentContext: null,
      seed: { kind: 'name', name: 'Special When Lit' },
      onsourcecreated: noop,
      oncancel: noop,
      onback: noop,
    });

    expect(screen.getByRole('button', { name: 'Video' })).toBeInTheDocument();
    // Year appears only once video is selected (a movie's main disambiguator).
    expect(screen.queryByLabelText(/Year/)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Video' }));
    await user.type(screen.getByLabelText(/Year/), '2009');

    await user.click(screen.getByRole('button', { name: /Continue/ }));
    await waitFor(() => expect(mockPOST).toHaveBeenCalled());
    expect(mockPOST).toHaveBeenCalledWith('/api/citation-sources/', {
      body: expect.objectContaining({
        name: 'Special When Lit',
        source_type: 'video',
        year: 2009,
        parent_id: null,
      }),
    });
  });

  it('a seed sourceType preselects the picker (the deliverer handoff)', () => {
    render(CitationCreateStage, {
      parentContext: null,
      seed: { kind: 'name', name: '', sourceType: 'video' },
      onsourcecreated: noop,
      oncancel: noop,
      onback: noop,
    });

    // Picker stays visible (the user can override), video selected, Year shown.
    expect(screen.getByRole('button', { name: 'Video' })).toHaveClass('selected');
    expect(screen.getByRole('button', { name: 'Book' })).not.toHaveClass('selected');
    expect(screen.getByLabelText(/Year/)).toBeInTheDocument();
  });

  it('shows the Slug field only for a slug-addressed type', async () => {
    const user = userEvent.setup();
    render(CitationCreateStage, {
      parentContext: null,
      seed: { kind: 'name', name: 'Billboard' },
      onsourcecreated: noop,
      oncancel: noop,
      onback: noop,
    });

    // Book (the default) is not slug-addressed — no Slug field.
    expect(screen.queryByLabelText(/Slug/)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Periodical' }));
    expect(screen.getByLabelText(/Slug/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Book' }));
    expect(screen.queryByLabelText(/Slug/)).not.toBeInTheDocument();
  });

  it('auto-proposes the slug from the name until the user diverges it', async () => {
    const user = userEvent.setup();
    render(CitationCreateStage, {
      parentContext: null,
      seed: { kind: 'name', name: '' },
      onsourcecreated: noop,
      oncancel: noop,
      onback: noop,
    });

    await user.click(screen.getByRole('button', { name: 'Periodical' }));
    await user.type(screen.getByLabelText('Name'), 'GameRoom Magazine');
    expect((screen.getByLabelText(/Slug/) as HTMLInputElement).value).toBe('gameroom-magazine');

    // Diverge the slug; further name edits no longer overwrite it.
    await user.clear(screen.getByLabelText(/Slug/));
    await user.type(screen.getByLabelText(/Slug/), 'gameroom');
    await user.type(screen.getByLabelText('Name'), ' Monthly');
    expect((screen.getByLabelText(/Slug/) as HTMLInputElement).value).toBe('gameroom');
  });

  it('clamps the proposed slug to the 200-char column limit', async () => {
    const user = userEvent.setup();
    const longName = 'Word '.repeat(60).trim(); // slugifies to ~299 chars
    render(CitationCreateStage, {
      parentContext: null,
      seed: { kind: 'name', name: longName },
      onsourcecreated: noop,
      oncancel: noop,
      onback: noop,
    });

    await user.click(screen.getByRole('button', { name: 'Periodical' }));
    const slug = (screen.getByLabelText(/Slug/) as HTMLInputElement).value;
    expect(slug.length).toBeLessThanOrEqual(200);
    expect(slug.length).toBeGreaterThan(190); // clamped near the limit, not emptied
    expect(slug.endsWith('-')).toBe(false); // the cut never leaves a trailing hyphen
  });

  it('reports the created source abstract flag to the orchestrator', async () => {
    const user = userEvent.setup();
    const onsourcecreated = vi.fn();
    mockPOST.mockResolvedValueOnce({
      data: {
        id: 70,
        name: 'Billboard',
        source_type: 'periodical',
        skip_locator: false,
        is_abstract: true,
        author: '',
        slug: 'billboard',
      },
    });
    render(CitationCreateStage, {
      parentContext: null,
      seed: { kind: 'name', name: 'Billboard' },
      onsourcecreated,
      oncancel: noop,
      onback: noop,
    });

    await user.click(screen.getByRole('button', { name: 'Periodical' }));
    await user.click(screen.getByRole('button', { name: /Continue/ }));
    await waitFor(() => expect(onsourcecreated).toHaveBeenCalled());
    expect(onsourcecreated).toHaveBeenCalledWith(
      expect.objectContaining({ isAbstract: true, author: '' }),
    );
  });

  it('submits the slug for a periodical and null for other types', async () => {
    const user = userEvent.setup();
    mockPOST.mockResolvedValueOnce({ data: CREATED_SOURCE });
    render(CitationCreateStage, {
      parentContext: null,
      seed: { kind: 'name', name: 'Billboard' },
      onsourcecreated: noop,
      oncancel: noop,
      onback: noop,
    });

    await user.click(screen.getByRole('button', { name: 'Periodical' }));
    await user.click(screen.getByRole('button', { name: /Continue/ }));
    await waitFor(() => expect(mockPOST).toHaveBeenCalled());
    expect(mockPOST).toHaveBeenCalledWith('/api/citation-sources/', {
      body: expect.objectContaining({
        name: 'Billboard',
        source_type: 'periodical',
        slug: 'billboard',
      }),
    });

    mockPOST.mockReset();
    mockPOST.mockResolvedValueOnce({ data: CREATED_SOURCE });
    await user.click(screen.getByRole('button', { name: 'Book' }));
    await user.click(screen.getByRole('button', { name: /Continue/ }));
    await waitFor(() => expect(mockPOST).toHaveBeenCalled());
    expect(mockPOST).toHaveBeenCalledWith('/api/citation-sources/', {
      body: expect.objectContaining({ source_type: 'book', slug: null }),
    });
  });

  it('an extraction (ISBN) draft prefills Publisher and Year; a manual name seed does not', () => {
    const { unmount } = render(CitationCreateStage, {
      parentContext: null,
      seed: {
        kind: 'extraction',
        draft: {
          name: 'Learning Python',
          source_type: 'book',
          author: 'Mark Lutz',
          publisher: "O'Reilly Media",
          year: 2009,
          isbn: '9780596517748',
        },
      },
      onsourcecreated: noop,
      oncancel: noop,
      onback: noop,
    });

    expect((screen.getByLabelText(/Author/) as HTMLInputElement).value).toBe('Mark Lutz');
    expect((screen.getByLabelText(/Publisher/) as HTMLInputElement).value).toBe("O'Reilly Media");
    expect((screen.getByLabelText(/Year/) as HTMLInputElement).value).toBe('2009');
    unmount();

    // A manual 'name' seed has no scraped metadata, so Publisher/Year are hidden.
    render(CitationCreateStage, {
      parentContext: null,
      seed: { kind: 'name', name: 'Manual Book' },
      onsourcecreated: noop,
      oncancel: noop,
      onback: noop,
    });
    expect(screen.queryByLabelText(/Publisher/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Year/)).not.toBeInTheDocument();
  });
});
