import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import type { CrossTitleLinkSchema } from '$lib/api/schema';
import RelatedTitlesSection from './RelatedTitlesSection.svelte';

describe('RelatedTitlesSection', () => {
  it('labels a cross-title bootleg_of link as "is a bootleg of"', () => {
    const relatedTitles: CrossTitleLinkSchema[] = [
      {
        relation: 'bootleg_of',
        other_title: { name: 'Video Pinball', public_id: 'video-pinball' },
        source_model: { name: 'Rugby', public_id: 'rugby-sidam' },
      },
    ];
    render(RelatedTitlesSection, { props: { relatedTitles } });

    expect(screen.getByText('Rugby')).toBeInTheDocument();
    expect(screen.getByText('is a bootleg of')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Video Pinball' })).toHaveAttribute(
      'href',
      expect.stringContaining('video-pinball'),
    );
  });
});
