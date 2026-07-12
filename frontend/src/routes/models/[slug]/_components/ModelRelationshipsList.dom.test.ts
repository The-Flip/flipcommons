import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import { makeModelDetail } from '$lib/api/detail-fixtures';
import ModelRelationshipsList from './ModelRelationshipsList.svelte';

describe('ModelRelationshipsList bootleg blocks', () => {
  it('renders the "Bootleg Of" block when the model is a bootleg', () => {
    const model = makeModelDetail({
      bootleg_of: { name: 'Video Pinball', public_id: 'video-pinball', year: 1978 },
    });
    render(ModelRelationshipsList, { props: { model } });

    const heading = screen.getByRole('heading', { name: 'Bootleg Of' });
    expect(heading).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'Video Pinball' });
    expect(link).toHaveAttribute('href', expect.stringContaining('video-pinball'));
  });

  it('renders the reverse "Bootlegs" block listing copies of this model', () => {
    const model = makeModelDetail({
      bootlegs: [{ name: 'Rugby', public_id: 'rugby-sidam', year: 1979 }],
    });
    render(ModelRelationshipsList, { props: { model } });

    expect(screen.getByRole('heading', { name: 'Bootlegs' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Rugby' })).toBeInTheDocument();
  });

  it('omits both bootleg blocks when there are no bootleg links', () => {
    render(ModelRelationshipsList, { props: { model: makeModelDetail() } });

    expect(screen.queryByRole('heading', { name: 'Bootleg Of' })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Bootlegs' })).not.toBeInTheDocument();
  });
});

describe('ModelRelationshipsList licensed-build blocks', () => {
  it('renders the "Licensed Build Of" block when the model is a licensed build', () => {
    const model = makeModelDetail({
      licensed_build_of: { name: 'Party Animal', public_id: 'party-animal', year: 1987 },
    });
    render(ModelRelationshipsList, { props: { model } });

    expect(screen.getByRole('heading', { name: 'Licensed Build Of' })).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'Party Animal' });
    expect(link).toHaveAttribute('href', expect.stringContaining('party-animal'));
  });

  it('renders the reverse "Licensed Builds" block listing licensed builds of this model', () => {
    const model = makeModelDetail({
      licensed_builds: [{ name: 'Party Animal', public_id: 'party-animal-2', year: 1987 }],
    });
    render(ModelRelationshipsList, { props: { model } });

    expect(screen.getByRole('heading', { name: 'Licensed Builds' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Party Animal' })).toHaveAttribute(
      'href',
      expect.stringContaining('party-animal-2'),
    );
  });

  it('omits both licensed-build blocks when there are no licensed-build links', () => {
    render(ModelRelationshipsList, { props: { model: makeModelDetail() } });

    expect(screen.queryByRole('heading', { name: 'Licensed Build Of' })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Licensed Builds' })).not.toBeInTheDocument();
  });
});
