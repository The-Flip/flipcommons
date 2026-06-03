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

import { validationErrorBody } from '$lib/api/error-fixtures';

import { saveModelClaims } from './save-model-claims';

describe('saveModelClaims', () => {
  beforeEach(() => {
    PATCH.mockReset();
    invalidateAll.mockReset();
  });

  it('returns ok and invalidates on success', async () => {
    PATCH.mockResolvedValue({ data: {}, error: undefined });
    invalidateAll.mockResolvedValue(undefined);

    const result = await saveModelClaims('medieval-madness', {
      fields: { description: 'new text' },
    });

    expect(result).toEqual({ ok: true });
    expect(PATCH).toHaveBeenCalledWith('/api/models/{public_id}/claims/', {
      params: { path: { public_id: 'medieval-madness' } },
      body: { fields: { description: 'new text' }, note: '' },
    });
    expect(invalidateAll).toHaveBeenCalledOnce();
  });

  it('extracts detail string from legacy error', async () => {
    PATCH.mockResolvedValue({
      data: undefined,
      error: { detail: 'Ensure this value is less than or equal to 999999.' },
    });

    const result = await saveModelClaims('medieval-madness', {
      fields: { ipdb_id: 10234567 },
    });

    expect(result).toEqual({
      ok: false,
      error: 'Ensure this value is less than or equal to 999999.',
      fieldErrors: {},
    });
    expect(invalidateAll).not.toHaveBeenCalled();
  });

  it('parses structured field errors from response', async () => {
    PATCH.mockResolvedValue({
      data: undefined,
      error: {
        detail: validationErrorBody({
          message: 'This value must be unique.',
          field_errors: { slug: 'This value must be unique.' },
        }),
      },
    });

    const result = await saveModelClaims('medieval-madness', {
      fields: { slug: 'other-game' },
    });

    expect(result).toEqual({
      ok: false,
      error: 'slug: This value must be unique.',
      fieldErrors: { slug: 'This value must be unique.' },
    });
  });

  it('parses a malformed-body 422 reshaped by the global ValidationError handler', async () => {
    // The backend ValidationError handler (config/api.py) reshapes
    // Pydantic's malformed-body errors into the structured envelope
    // with field keys derived from `loc[-1]`.
    PATCH.mockResolvedValue({
      data: undefined,
      error: {
        detail: validationErrorBody({
          message: 'Invalid request.',
          field_errors: { year: 'Input should be a valid integer' },
        }),
      },
    });

    const result = await saveModelClaims('medieval-madness', {
      fields: { year: 'not-a-number' },
    });

    expect(result).toEqual({
      ok: false,
      error: 'year: Input should be a valid integer',
      fieldErrors: { year: 'Input should be a valid integer' },
    });
  });

  it('handles string errors', async () => {
    PATCH.mockResolvedValue({ data: undefined, error: 'Something went wrong' });

    const result = await saveModelClaims('medieval-madness', {
      fields: { description: 'x' },
    });

    expect(result).toEqual({ ok: false, error: 'Something went wrong', fieldErrors: {} });
  });

  it('falls back to JSON for unknown error shapes', async () => {
    PATCH.mockResolvedValue({ data: undefined, error: { unexpected: 'shape' } });

    const result = await saveModelClaims('medieval-madness', {
      fields: { description: 'x' },
    });

    expect(result).toEqual({ ok: false, error: '{"unexpected":"shape"}', fieldErrors: {} });
  });

  it('sends credits-only body with default fields', async () => {
    PATCH.mockResolvedValue({ data: {}, error: undefined });
    invalidateAll.mockResolvedValue(undefined);

    const credits = [{ person_slug: 'pat-lawlor', role: 'game-design' }];
    await saveModelClaims('medieval-madness', { credits });

    expect(PATCH).toHaveBeenCalledWith('/api/models/{public_id}/claims/', {
      params: { path: { public_id: 'medieval-madness' } },
      body: { fields: {}, note: '', credits },
    });
  });

  it('passes note override', async () => {
    PATCH.mockResolvedValue({ data: {}, error: undefined });
    invalidateAll.mockResolvedValue(undefined);

    await saveModelClaims('medieval-madness', {
      fields: { year: 1997 },
      note: 'Corrected per IPDB',
    });

    expect(PATCH).toHaveBeenCalledWith('/api/models/{public_id}/claims/', {
      params: { path: { public_id: 'medieval-madness' } },
      body: { fields: { year: 1997 }, note: 'Corrected per IPDB' },
    });
  });

  it('passes citation override', async () => {
    PATCH.mockResolvedValue({ data: {}, error: undefined });
    invalidateAll.mockResolvedValue(undefined);

    const citation = { citation_instance_id: 42 };
    await saveModelClaims('medieval-madness', {
      fields: { year: 1997 },
      citation,
    });

    expect(PATCH).toHaveBeenCalledWith('/api/models/{public_id}/claims/', {
      params: { path: { public_id: 'medieval-madness' } },
      body: { fields: { year: 1997 }, note: '', citation },
    });
  });
});
