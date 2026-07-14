import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import { makeModelDetail } from '$lib/api/detail-fixtures';
import ModelRelationshipsList from './ModelRelationshipsList.svelte';

describe('ModelRelationshipsList relationship edges', () => {
  it('renders an outbound machine-target edge as a lead heading with a linked target', () => {
    const model = makeModelDetail({
      relationships: [
        {
          relationship_type: 'conversion_kit',
          license_status: 'unknown',
          target_machine: {
            name: 'Galaxie',
            public_id: 'galaxie',
            year: 1971,
            manufacturer: { name: 'Gottlieb', public_id: 'gottlieb' },
          },
          target_label: '',
        },
      ],
    });
    render(ModelRelationshipsList, { props: { model } });

    expect(screen.getByRole('heading', { name: 'Conversion kit for' })).toBeInTheDocument();
    // Rendered like every lineage link: name link + maker link + year.
    const link = screen.getByRole('link', { name: 'Galaxie' });
    expect(link).toHaveAttribute('href', expect.stringContaining('galaxie'));
    expect(screen.getByRole('link', { name: 'Gottlieb' })).toHaveAttribute(
      'href',
      expect.stringContaining('gottlieb'),
    );
    expect(screen.getByText(/1971/)).toBeInTheDocument();
  });

  it('renders a label-target edge as plain text with no hyperlink', () => {
    const model = makeModelDetail({
      relationships: [
        {
          relationship_type: 'conversion_kit',
          license_status: 'unknown',
          target_machine: null,
          target_label: 'several Gottlieb EM models',
        },
      ],
    });
    render(ModelRelationshipsList, { props: { model } });

    expect(screen.getByText('several Gottlieb EM models')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Gottlieb/ })).not.toBeInTheDocument();
  });

  it('renders an inbound edge under its plural heading with a linked source', () => {
    const model = makeModelDetail({
      inbound_relationships: [
        {
          relationship_type: 'copy',
          license_status: 'unlicensed',
          source_machine: { name: 'Rugby', public_id: 'rugby-sidam', year: 1979 },
        },
      ],
    });
    render(ModelRelationshipsList, { props: { model } });

    expect(screen.getByRole('heading', { name: 'Bootlegs' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Rugby' })).toHaveAttribute(
      'href',
      expect.stringContaining('rugby-sidam'),
    );
  });

  it('omits edge sections when the model has no edges', () => {
    render(ModelRelationshipsList, { props: { model: makeModelDetail() } });

    expect(screen.queryByRole('heading', { name: 'Bootlegs' })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /Conversion kit/ })).not.toBeInTheDocument();
  });
});
