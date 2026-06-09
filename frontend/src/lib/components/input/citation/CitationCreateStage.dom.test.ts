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
      prefillName: 'Elton John product page',
      onsourcecreated: noop,
      oncancel: noop,
      onback: noop,
    });

    await user.type(
      screen.getByPlaceholderText('URL'),
      'https://jerseyjackpinball.com/products/elton-john',
    );
    await user.click(screen.getByRole('button', { name: /Create & cite/ }));

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
      prefillName: 'Some Site',
      onsourcecreated: noop,
      oncancel: noop,
      onback: noop,
    });

    await user.click(screen.getByRole('button', { name: 'web' }));
    await user.type(screen.getByPlaceholderText('URL'), 'https://somesite.com/');
    await user.click(screen.getByRole('button', { name: /Create & cite/ }));

    await waitFor(() => expect(mockPOST).toHaveBeenCalled());
    expect(mockPOST).toHaveBeenCalledWith('/api/citation-sources/', {
      body: expect.objectContaining({ parent_id: null, link_type: 'homepage' }),
    });
  });
});
