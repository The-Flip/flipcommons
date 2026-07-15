import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import type { CrossTitleLinkSchema } from '$lib/api/schema';
import RelatedTitlesSection from './RelatedTitlesSection.svelte';

describe('RelatedTitlesSection', () => {
  it('labels a cross-title remake_of link as "is a remake of"', () => {
    const relatedTitles: CrossTitleLinkSchema[] = [
      {
        relation: 'remake_of',
        license_status: 'unknown',
        other_title: { name: 'Video Pinball', public_id: 'video-pinball' },
        source_model: { name: 'Rugby', public_id: 'rugby-sidam' },
      },
    ];
    render(RelatedTitlesSection, { props: { relatedTitles } });

    expect(screen.getByText('Rugby')).toBeInTheDocument();
    expect(screen.getByText('is a remake of')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Video Pinball' })).toHaveAttribute(
      'href',
      expect.stringContaining('video-pinball'),
    );
  });

  it('phrases a relationship edge from its (kind, license), e.g. "is a bootleg of"', () => {
    const relatedTitles: CrossTitleLinkSchema[] = [
      {
        relation: 'copy',
        license_status: 'unlicensed',
        other_title: { name: 'Galaxie', public_id: 'galaxie' },
        source_model: { name: 'Galaxie RMG', public_id: 'galaxie-rmg-1' },
      },
      {
        relation: 'conversion',
        license_status: 'unlicensed',
        other_title: { name: 'Hi-Score', public_id: 'hi-score' },
        source_model: { name: 'Musketeers', public_id: 'musketeers' },
      },
      {
        relation: 'conversion_kit',
        license_status: 'licensed',
        other_title: { name: 'Team One', public_id: 'team-one' },
        source_model: { name: 'Wizard', public_id: 'wizard-4' },
      },
    ];
    render(RelatedTitlesSection, { props: { relatedTitles } });

    expect(screen.getByText('is a bootleg of')).toBeInTheDocument();
    // The article flexes with the phrase's first sound.
    expect(screen.getByText('is an unlicensed conversion of')).toBeInTheDocument();
    expect(screen.getByText('is a licensed conversion kit for')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Galaxie' })).toHaveAttribute(
      'href',
      expect.stringContaining('galaxie'),
    );
  });

  const oneLink: CrossTitleLinkSchema[] = [
    {
      relation: 'remake_of',
      license_status: 'unknown',
      other_title: { name: 'Video Pinball', public_id: 'video-pinball' },
      source_model: { name: 'Rugby', public_id: 'rugby-sidam' },
    },
  ];

  it('wraps the list in a titled sidebar section by default (desktop sidebar)', () => {
    render(RelatedTitlesSection, { props: { relatedTitles: oneLink } });

    expect(screen.getByRole('heading', { name: 'Related Titles' })).toBeInTheDocument();
  });

  it('omits its own heading when inline (the accordion supplies one)', () => {
    render(RelatedTitlesSection, { props: { relatedTitles: oneLink, inline: true } });

    expect(screen.queryByRole('heading', { name: 'Related Titles' })).not.toBeInTheDocument();
    // The lines still render.
    expect(screen.getByRole('link', { name: 'Video Pinball' })).toBeInTheDocument();
  });
});
