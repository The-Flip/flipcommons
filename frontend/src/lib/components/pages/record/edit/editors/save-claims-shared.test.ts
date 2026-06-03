import { beforeEach, describe, expect, it, vi } from 'vitest';

import { validationErrorBody } from '$lib/api/error-fixtures';

import { saveHierarchicalTaxonomyClaims, saveSimpleTaxonomyClaims } from './save-claims-shared';

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

describe('saveSimpleTaxonomyClaims', () => {
  beforeEach(() => {
    PATCH.mockReset();
    invalidateAll.mockReset();
    invalidateAll.mockResolvedValue(undefined);
  });

  it('PATCHes the supplied claims endpoint with the merged body', async () => {
    PATCH.mockResolvedValueOnce({ data: { slug: 'widebody' }, error: undefined });

    const result = await saveSimpleTaxonomyClaims(
      '/api/cabinets/{public_id}/claims/',
      'wide-body',
      {
        fields: { slug: 'widebody' },
      },
    );

    expect(PATCH).toHaveBeenCalledWith('/api/cabinets/{public_id}/claims/', {
      params: { path: { public_id: 'wide-body' } },
      body: { fields: { slug: 'widebody' }, note: '' },
    });
    expect(invalidateAll).toHaveBeenCalledTimes(1);
    expect(result).toEqual({ ok: true, updatedSlug: 'widebody' });
  });

  it('falls back to the original slug when the response omits one', async () => {
    PATCH.mockResolvedValueOnce({ data: undefined, error: undefined });

    const result = await saveSimpleTaxonomyClaims('/api/tags/{public_id}/claims/', 'arcade', {
      fields: {},
    });

    expect(result).toEqual({ ok: true, updatedSlug: 'arcade' });
  });

  it('returns a parsed error on failure and skips invalidateAll', async () => {
    PATCH.mockResolvedValueOnce({
      data: undefined,
      error: {
        detail: validationErrorBody({ message: 'nope', field_errors: { slug: 'taken' } }),
      },
    });

    const result = await saveSimpleTaxonomyClaims('/api/series/{public_id}/claims/', 'foo', {
      fields: { slug: 'other' },
    });

    expect(result).toEqual({ ok: false, error: 'slug: taken', fieldErrors: { slug: 'taken' } });
    expect(invalidateAll).not.toHaveBeenCalled();
  });

  it('forwards the citation field when supplied', async () => {
    PATCH.mockResolvedValueOnce({ data: { slug: 'foo' }, error: undefined });

    await saveSimpleTaxonomyClaims('/api/franchises/{public_id}/claims/', 'foo', {
      fields: { name: 'Foo' },
      note: 'rename',
      citation: { citation_instance_id: 42 },
    });

    expect(PATCH).toHaveBeenCalledWith('/api/franchises/{public_id}/claims/', {
      params: { path: { public_id: 'foo' } },
      body: {
        fields: { name: 'Foo' },
        note: 'rename',
        citation: { citation_instance_id: 42 },
      },
    });
  });
});

describe('saveHierarchicalTaxonomyClaims', () => {
  beforeEach(() => {
    PATCH.mockReset();
    invalidateAll.mockReset();
    invalidateAll.mockResolvedValue(undefined);
  });

  it('PATCHes the supplied claims endpoint with the merged body', async () => {
    PATCH.mockResolvedValueOnce({ data: { slug: 'medieval' }, error: undefined });

    const result = await saveHierarchicalTaxonomyClaims(
      '/api/themes/{public_id}/claims/',
      'medieval',
      {
        fields: { name: 'Medieval' },
      },
    );

    expect(PATCH).toHaveBeenCalledWith('/api/themes/{public_id}/claims/', {
      params: { path: { public_id: 'medieval' } },
      body: { fields: { name: 'Medieval' }, note: '' },
    });
    expect(invalidateAll).toHaveBeenCalledTimes(1);
    expect(result).toEqual({ ok: true, updatedSlug: 'medieval' });
  });

  it('forwards parents and aliases when supplied', async () => {
    PATCH.mockResolvedValueOnce({ data: { slug: 'pop-bumper' }, error: undefined });

    await saveHierarchicalTaxonomyClaims(
      '/api/gameplay-features/{public_id}/claims/',
      'pop-bumper',
      {
        parents: ['physical-feature'],
        aliases: ['Pop'],
        note: 'rationale',
      },
    );

    expect(PATCH).toHaveBeenCalledWith('/api/gameplay-features/{public_id}/claims/', {
      params: { path: { public_id: 'pop-bumper' } },
      body: {
        fields: {},
        note: 'rationale',
        parents: ['physical-feature'],
        aliases: ['Pop'],
      },
    });
  });

  it('returns parsed field errors on 422 and skips invalidateAll', async () => {
    PATCH.mockResolvedValueOnce({
      data: undefined,
      error: {
        detail: validationErrorBody({
          message: 'invalid',
          field_errors: { parents: 'would create a cycle' },
        }),
      },
    });

    const result = await saveHierarchicalTaxonomyClaims(
      '/api/themes/{public_id}/claims/',
      'medieval',
      {
        parents: ['descendant-of-medieval'],
      },
    );

    expect(result).toEqual({
      ok: false,
      error: 'parents: would create a cycle',
      fieldErrors: { parents: 'would create a cycle' },
    });
    expect(invalidateAll).not.toHaveBeenCalled();
  });
});
