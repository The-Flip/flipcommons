import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import CitationCreateStage from './CitationCreateStage.svelte';
import { CREATED_SOURCE } from './citation-fixtures';

const { mockPOST } = vi.hoisted(() => ({ mockPOST: vi.fn() }));
vi.mock('$lib/api/client', () => ({ default: { POST: mockPOST } }));

const WEB_ROOT_PARENT = {
  id: 30,
  name: 'Jersey Jack',
  source_type: 'web',
  author: '',
  identifier_key: '',
};

function noop() {}

beforeEach(() => mockPOST.mockReset());

describe('CitationCreateStage link_type', () => {
  it('posts reference for a web child created under a parent root', async () => {
    // A child is a specific page, not the source's homepage — 'reference' keeps
    // it from masquerading as a domain root in later URL recognition.
    const user = userEvent.setup();
    mockPOST.mockResolvedValueOnce({ data: CREATED_SOURCE });
    render(CitationCreateStage, {
      parentContext: WEB_ROOT_PARENT,
      seed: { kind: 'name', name: 'Elton John product page' },
      onsourcecreated: noop,
      oncancel: noop,
      onback: noop,
    });

    await user.type(
      screen.getByLabelText('URL'),
      'https://jerseyjackpinball.com/products/elton-john',
    );
    // A web child (under a parent) cites on submit, so the button says so.
    await user.click(screen.getByRole('button', { name: /Create Citation/ }));

    await waitFor(() => expect(mockPOST).toHaveBeenCalled());
    expect(mockPOST).toHaveBeenCalledWith('/api/citation-sources/', {
      body: expect.objectContaining({
        parent_id: WEB_ROOT_PARENT.id,
        link_type: 'reference',
      }),
    });
  });

  it('posts homepage for a new root web source (no parent)', async () => {
    const user = userEvent.setup();
    mockPOST.mockResolvedValueOnce({ data: CREATED_SOURCE });
    render(CitationCreateStage, {
      parentContext: null,
      seed: { kind: 'name', name: 'Some Site' },
      onsourcecreated: noop,
      oncancel: noop,
      onback: noop,
    });

    await user.click(screen.getByRole('button', { name: 'web' }));
    await user.type(screen.getByLabelText('URL'), 'https://somesite.com/');
    // A parentless web root advances to the locator next, so the button says "Continue".
    await user.click(screen.getByRole('button', { name: /Continue/ }));

    await waitFor(() => expect(mockPOST).toHaveBeenCalled());
    expect(mockPOST).toHaveBeenCalledWith('/api/citation-sources/', {
      body: expect.objectContaining({ parent_id: null, link_type: 'homepage' }),
    });
  });
});

describe('CitationCreateStage seed rendering', () => {
  const WEB_DRAFT = {
    name: 'Pinball - Wikipedia',
    source_type: 'web',
    author: '',
    publisher: 'Wikipedia',
    year: null,
    isbn: null,
    url: 'https://en.wikipedia.org/wiki/Pinball',
  };

  it('extraction seed: Page Name + read-only URL, no Publisher/Year, retrieval note', () => {
    render(CitationCreateStage, {
      parentContext: null,
      seed: { kind: 'extraction', draft: WEB_DRAFT },
      onsourcecreated: noop,
      oncancel: noop,
      onback: noop,
    });

    // Web source: the name field is "Page Name", prefilled from the scrape.
    expect((screen.getByLabelText('Page Name') as HTMLInputElement).value).toBe(
      'Pinball - Wikipedia',
    );
    // The URL is shown for confirmation but read-only (the user already pasted it).
    const urlInput = screen.getByLabelText('URL') as HTMLInputElement;
    expect(urlInput.value).toBe('https://en.wikipedia.org/wiki/Pinball');
    expect(urlInput.readOnly).toBe(true);
    // Publisher and Year are hidden for web.
    expect(screen.queryByLabelText(/publisher/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/year/i)).not.toBeInTheDocument();
    expect(screen.getByText(/Retrieved from page/i)).toBeInTheDocument();
  });

  it('extraction seed with no title: blank Page Name, no retrieval note', () => {
    // A scrape that returned 200 but found no og:title/<title> yields an empty
    // name — there's nothing to "review", so the note is omitted.
    render(CitationCreateStage, {
      parentContext: null,
      seed: { kind: 'extraction', draft: { ...WEB_DRAFT, name: '' } },
      onsourcecreated: noop,
      oncancel: noop,
      onback: noop,
    });

    expect((screen.getByLabelText('Page Name') as HTMLInputElement).value).toBe('');
    expect(screen.queryByText(/Retrieved from page/i)).not.toBeInTheDocument();
  });

  it('web-url seed (failed scrape): blank Page Name, editable prefilled URL', () => {
    render(CitationCreateStage, {
      parentContext: null,
      seed: { kind: 'web-url', url: 'https://example.com/article' },
      onsourcecreated: noop,
      oncancel: noop,
      onback: noop,
    });

    // No title was found, so Page Name is blank for the user to fill.
    expect((screen.getByLabelText('Page Name') as HTMLInputElement).value).toBe('');
    const urlInput = screen.getByLabelText('URL') as HTMLInputElement;
    expect(urlInput.value).toBe('https://example.com/article');
    // A failed scrape is exactly when the URL may be mistyped, so it stays editable.
    expect(urlInput.readOnly).toBe(false);
    // Not an extraction, so no retrieval note.
    expect(screen.queryByText(/Retrieved from page/i)).not.toBeInTheDocument();
  });
});
