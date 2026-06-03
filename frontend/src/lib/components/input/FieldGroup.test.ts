import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';

import DuplicateIdsFixture from './FieldGroup.duplicate-ids.fixture.svelte';

describe('FieldGroup', () => {
  it('generates unique fallback ids for repeated labels', () => {
    const { body } = render(DuplicateIdsFixture);
    const ids = [...body.matchAll(/<input[^>]* id="([^"]+)"/g)].map((match) => match[1]);
    const labels = [...body.matchAll(/<label[^>]* for="([^"]+)"/g)].map((match) => match[1]);

    expect(ids).toHaveLength(2);
    expect(new Set(ids).size).toBe(2);
    expect(labels).toEqual(ids);
  });
});
