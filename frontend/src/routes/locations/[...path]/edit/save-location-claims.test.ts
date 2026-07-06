import { beforeEach, describe, expect, it, vi } from 'vitest';

import { validationErrorBody } from '$lib/api/error-fixtures';

import { saveLocationClaims } from './save-location-claims';

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

describe('saveLocationClaims', () => {
  beforeEach(() => {
    PATCH.mockReset();
    invalidateAll.mockReset();
    invalidateAll.mockResolvedValue(undefined);
  });

  it('PATCHes the locations claims endpoint with public_id (not slug) as the path param', async () => {
    PATCH.mockResolvedValueOnce({ data: { public_id: 'usa/il/chicago' }, error: undefined });

    const result = await saveLocationClaims('usa/il/chicago', {
      fields: { description: 'Windy City' },
    });

    expect(PATCH).toHaveBeenCalledTimes(1);
    const [path, options] = PATCH.mock.calls[0];
    expect(path).toBe('/api/locations/{public_id}/claims/');
    // Multi-segment public_id rides through unchanged — the openapi-fetch
    // middleware preserves slashes in path params.
    expect(options.params.path).toEqual({ public_id: 'usa/il/chicago' });
    // No `slug` key — Location's identity field is `public_id`, not `slug`.
    expect(options.params.path).not.toHaveProperty('slug');
    expect(options.body).toEqual({
      fields: { description: 'Windy City' },
      note: '',
      citations: [],
      inline_citations: [],
    });
    expect(invalidateAll).toHaveBeenCalledTimes(1);
    expect(result).toEqual({ ok: true, updatedSlug: 'usa/il/chicago' });
  });

  it('forwards aliases payloads', async () => {
    PATCH.mockResolvedValueOnce({ data: { public_id: 'usa' }, error: undefined });

    const result = await saveLocationClaims('usa', {
      aliases: ['United States', 'America'],
    });

    expect(PATCH).toHaveBeenCalledWith('/api/locations/{public_id}/claims/', {
      params: { path: { public_id: 'usa' } },
      body: {
        fields: {},
        note: '',
        citations: [],
        inline_citations: [],
        aliases: ['United States', 'America'],
      },
    });
    expect(result).toEqual({ ok: true, updatedSlug: 'usa' });
  });

  it('forwards top-level divisions payloads (country-only field)', async () => {
    PATCH.mockResolvedValueOnce({ data: { public_id: 'usa' }, error: undefined });

    const result = await saveLocationClaims('usa', {
      divisions: ['state', 'city'],
    });

    expect(PATCH).toHaveBeenCalledWith('/api/locations/{public_id}/claims/', {
      params: { path: { public_id: 'usa' } },
      body: {
        fields: {},
        note: '',
        citations: [],
        inline_citations: [],
        divisions: ['state', 'city'],
      },
    });
    expect(result).toEqual({ ok: true, updatedSlug: 'usa' });
  });

  it('falls back to the request public_id when the response omits one', async () => {
    PATCH.mockResolvedValueOnce({ data: undefined, error: undefined });

    const result = await saveLocationClaims('usa/il', { fields: {} });

    expect(result).toEqual({ ok: true, updatedSlug: 'usa/il' });
  });

  it('returns a parsed error on failure and skips invalidateAll', async () => {
    PATCH.mockResolvedValueOnce({
      data: undefined,
      error: {
        detail: validationErrorBody({
          message: 'divisions only on countries',
          field_errors: { divisions: 'only on countries' },
        }),
      },
    });

    const result = await saveLocationClaims('usa/il', {
      divisions: ['neighborhood'],
    });

    expect(result).toEqual({
      ok: false,
      error: 'divisions: only on countries',
      fieldErrors: { divisions: 'only on countries' },
    });
    expect(invalidateAll).not.toHaveBeenCalled();
  });
});
