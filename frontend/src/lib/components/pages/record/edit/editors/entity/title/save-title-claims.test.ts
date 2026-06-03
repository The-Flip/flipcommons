import { describe, expect, it, vi, beforeEach } from 'vitest';

const { PATCH } = vi.hoisted(() => ({
  PATCH: vi.fn(),
}));

const { invalidateAll } = vi.hoisted(() => ({
  invalidateAll: vi.fn(),
}));

vi.mock('$lib/api/client', () => ({
  default: { PATCH },
}));

vi.mock('$app/navigation', () => ({
  invalidateAll,
}));

import { saveTitleClaims } from './save-title-claims';

describe('saveTitleClaims', () => {
  beforeEach(() => {
    PATCH.mockReset();
    invalidateAll.mockReset();
  });

  it('PATCHes /api/titles/{public_id}/claims/ and invalidates on success', async () => {
    PATCH.mockResolvedValue({ data: {}, error: undefined });
    invalidateAll.mockResolvedValue(undefined);

    const result = await saveTitleClaims('addams-family', {
      fields: { description: 'new text' },
    });

    expect(result).toEqual({ ok: true });
    expect(PATCH).toHaveBeenCalledWith('/api/titles/{public_id}/claims/', {
      params: { path: { public_id: 'addams-family' } },
      body: { fields: { description: 'new text' }, note: '' },
    });
    expect(invalidateAll).toHaveBeenCalledOnce();
  });

  it('returns parsed error and skips invalidation on failure', async () => {
    PATCH.mockResolvedValue({
      data: undefined,
      error: { detail: 'Something went wrong' },
    });

    const result = await saveTitleClaims('addams-family', {
      fields: { description: 'x' },
    });

    expect(result).toEqual({
      ok: false,
      error: 'Something went wrong',
      fieldErrors: {},
    });
    expect(invalidateAll).not.toHaveBeenCalled();
  });

  it('passes abbreviations through with default fields and note', async () => {
    PATCH.mockResolvedValue({ data: {}, error: undefined });
    invalidateAll.mockResolvedValue(undefined);

    const abbreviations = ['TAF'];
    await saveTitleClaims('addams-family', { abbreviations });

    expect(PATCH).toHaveBeenCalledWith('/api/titles/{public_id}/claims/', {
      params: { path: { public_id: 'addams-family' } },
      body: { fields: {}, note: '', abbreviations },
    });
  });
});
