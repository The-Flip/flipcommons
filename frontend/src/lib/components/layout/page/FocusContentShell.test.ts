import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';

import Harness from './FocusContentShell.test-harness.svelte';

describe('FocusContentShell', () => {
  it('renders the back link, heading slot, and children', () => {
    const { body } = render(Harness, {
      props: { backHref: '/titles/medieval-madness' },
    });

    expect(body).toContain('href="/titles/medieval-madness"');
    expect(body).toContain('Back');
    expect(body).toContain('<h1>Edit History</h1>');
    expect(body).toContain('Audit content');
  });

  it('renders the record name as a link when provided', () => {
    const { body } = render(Harness, {
      props: {
        backHref: '/titles/medieval-madness',
        recordName: 'Medieval Madness',
        recordHref: '/titles/medieval-madness',
      },
    });

    expect(body).toContain('Medieval Madness');
    expect(body).toContain('title="Medieval Madness"');
  });

  it('omits the record name when not provided', () => {
    const { body } = render(Harness, {
      props: { backHref: '/titles/medieval-madness' },
    });

    expect(body).not.toContain('class="record-name"');
  });

  it('applies a custom max-width when provided', () => {
    const { body } = render(Harness, {
      props: { maxWidth: '64rem' },
    });

    expect(body).toContain('max-width: 64rem');
  });

  it('uses the default max-width when none is provided', () => {
    const { body } = render(Harness, {});

    expect(body).toContain('max-width: 48rem');
  });
});
