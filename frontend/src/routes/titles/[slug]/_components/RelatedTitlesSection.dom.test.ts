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

  it('labels a cross-title licensed_build_of link as "is a licensed build of"', () => {
    const relatedTitles: CrossTitleLinkSchema[] = [
      {
        relation: 'licensed_build_of',
        other_title: { name: 'Party Animal', public_id: 'party-animal' },
        source_model: { name: 'Party Animal', public_id: 'party-animal-2' },
      },
    ];
    render(RelatedTitlesSection, { props: { relatedTitles } });

    expect(screen.getByText('is a licensed build of')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Party Animal' })).toHaveAttribute(
      'href',
      expect.stringContaining('party-animal'),
    );
  });
});
