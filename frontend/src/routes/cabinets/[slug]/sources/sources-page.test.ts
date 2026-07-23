import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';

import Harness from './sources-page.test-harness.svelte';

describe('cabinet sources page (taxonomy representative)', () => {
  it('wraps EntitySources in FocusContentShell with back link to detail and a Sources heading', () => {
    const { body } = render(Harness, {
      props: { data: { sources: [] } },
    });

    expect(body).toContain('href="/cabinets/standard-body"');
    expect(body).toContain('Back');
    expect(body).toContain('>Sources</h1>');
    expect(body.toLowerCase()).toContain('no source data recorded yet');
  });
});
