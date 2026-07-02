import { beforeEach, describe, expect, it, vi } from 'vitest';

import { validationErrorBody } from '$lib/api/error-fixtures';

import { saveCorporateEntityClaims } from './save-corporate-entity-claims';

const { PATCH, invalidateAll } = vi.hoisted(() => ({
  PATCH: vi.fn(),
  invalidateAll: vi.fn(),
}));

vi.mock('$lib/api/client', () => ({
  default: { PATCH },
}));

vi.mock('$app/navigation', () => ({
  invalidateAll,
}));

describe('saveCorporateEntityClaims', () => {
  beforeEach(() => {
    PATCH.mockReset();
    invalidateAll.mockReset();
    invalidateAll.mockResolvedValue(undefined);
  });

  it('PATCHes the corporate-entities claims endpoint with the supplied body', async () => {
    PATCH.mockResolvedValueOnce({ data: { slug: 'williams-electronics' }, error: undefined });

    const result = await saveCorporateEntityClaims('williams-elec', {
      fields: { name: 'Williams Electronics', slug: 'williams-electronics' },
    });

    expect(PATCH).toHaveBeenCalledWith('/api/corporate-entities/{public_id}/claims/', {
      params: { path: { public_id: 'williams-elec' } },
      body: {
        fields: { name: 'Williams Electronics', slug: 'williams-electronics' },
        note: '',
        citations: [],
      },
    });
    expect(invalidateAll).toHaveBeenCalledTimes(1);
    expect(result).toEqual({ ok: true, updatedSlug: 'williams-electronics' });
  });

  it('forwards aliases payloads', async () => {
    PATCH.mockResolvedValueOnce({ data: { slug: 'williams' }, error: undefined });

    const result = await saveCorporateEntityClaims('williams', {
      aliases: ['WMS', 'Williams Inc'],
    });

    expect(PATCH).toHaveBeenCalledWith('/api/corporate-entities/{public_id}/claims/', {
      params: { path: { public_id: 'williams' } },
      body: { fields: {}, note: '', citations: [], aliases: ['WMS', 'Williams Inc'] },
    });
    expect(result).toEqual({ ok: true, updatedSlug: 'williams' });
  });

  it('falls back to the original slug when the response omits one', async () => {
    PATCH.mockResolvedValueOnce({ data: undefined, error: undefined });

    const result = await saveCorporateEntityClaims('williams', { fields: {} });

    expect(result).toEqual({ ok: true, updatedSlug: 'williams' });
  });

  it('returns a parsed error on failure and skips invalidateAll', async () => {
    PATCH.mockResolvedValueOnce({
      data: undefined,
      error: {
        detail: validationErrorBody({ message: 'nope', field_errors: { slug: 'taken' } }),
      },
    });

    const result = await saveCorporateEntityClaims('williams', { fields: { slug: 'bally' } });

    expect(result).toEqual({ ok: false, error: 'slug: taken', fieldErrors: { slug: 'taken' } });
    expect(invalidateAll).not.toHaveBeenCalled();
  });
});
