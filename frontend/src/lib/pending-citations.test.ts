import { describe, expect, it, vi } from 'vitest';

const { mockPOST } = vi.hoisted(() => ({ mockPOST: vi.fn() }));

vi.mock('$lib/api/client', () => ({
  default: { POST: mockPOST },
}));

import {
  buildInlineCitationsRequest,
  pendingCitationsInText,
  reserveCitationSlug,
  type PendingInlineCitation,
} from './pending-citations';

function pending(
  slug: string,
  overrides: Partial<PendingInlineCitation> = {},
): PendingInlineCitation {
  return {
    slug,
    sourceId: 1,
    sourceName: 'The Encyclopedia of Pinball',
    sourceType: 'book',
    locator: '',
    quote: '',
    ...overrides,
  };
}

describe('reserveCitationSlug', () => {
  it('POSTs the reservation endpoint and returns the slug', async () => {
    mockPOST.mockResolvedValueOnce({ data: { slug: 'bqntvkrs' } });
    await expect(reserveCitationSlug()).resolves.toBe('bqntvkrs');
    expect(mockPOST).toHaveBeenCalledWith('/api/citation-instances/reservations/', {});
  });

  it('throws when the reservation fails', async () => {
    mockPOST.mockResolvedValueOnce({ error: 'nope' });
    await expect(reserveCitationSlug()).rejects.toThrow();
  });
});

describe('pendingCitationsInText', () => {
  it('keeps only cites whose marker survives in the text, in document order', () => {
    const a = pending('aaaaaaaa');
    const b = pending('bbbbbbbb');
    const result = pendingCitationsInText(
      [a, b],
      'Second.[[cite:bbbbbbbb]] First.[[cite:aaaaaaaa]]',
    );
    expect(result).toEqual([b, a]);
  });

  it('drops cites whose marker was deleted', () => {
    const kept = pending('kkkkkkkk');
    const removed = pending('rrrrrrrr');
    expect(pendingCitationsInText([kept, removed], 'Only.[[cite:kkkkkkkk]]')).toEqual([kept]);
  });

  it('ignores markers with no pending entry (already-saved cites)', () => {
    expect(pendingCitationsInText([], 'Saved.[[cite:ssssssss]]')).toEqual([]);
  });
});

describe('buildInlineCitationsRequest', () => {
  it('builds wire-shape specs for surviving markers only', () => {
    const kept = pending('kkkkkkkk', { sourceId: 7, locator: 'p. 3', quote: 'Verbatim.' });
    const removed = pending('rrrrrrrr');
    const specs = buildInlineCitationsRequest([kept, removed], 'Only.[[cite:kkkkkkkk]]');
    expect(specs).toEqual([
      { slug: 'kkkkkkkk', citation_source_id: 7, locator: 'p. 3', quote: 'Verbatim.' },
    ]);
  });

  it('returns an empty list when nothing is pending', () => {
    expect(buildInlineCitationsRequest([], 'Plain text.')).toEqual([]);
  });
});
