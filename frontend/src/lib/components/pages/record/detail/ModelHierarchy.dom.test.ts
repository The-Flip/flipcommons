import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import ModelHierarchy from './ModelHierarchy.svelte';

const stern = { name: 'Stern', public_id: 'stern' };

describe('ModelHierarchy manufacturer disambiguation', () => {
  it('surfaces "Unknown Manufacturer" for a model whose manufacturer is unknown against a known subject', () => {
    render(ModelHierarchy, {
      props: {
        models: [{ name: 'Retheme', public_id: 'retheme', variants: [] }],
        subjectManufacturer: 'Stern',
      },
    });

    expect(screen.getByText(/Unknown Manufacturer/)).toBeInTheDocument();
  });

  it('does not infer an unknown manufacturer for a variant, which inherits its parent’s', () => {
    // The variant projection carries no manufacturer field; it should inherit the
    // parent's (Stern) rather than read the missing field as genuinely unknown.
    render(ModelHierarchy, {
      props: {
        models: [
          {
            name: 'Premium',
            public_id: 'premium',
            manufacturer: stern,
            variants: [{ name: 'Limited Edition', public_id: 'le' }],
          },
        ],
        subjectManufacturer: 'Stern',
      },
    });

    expect(screen.getByRole('link', { name: 'Limited Edition' })).toBeInTheDocument();
    // Parent and variant both match the subject's manufacturer, so neither shows one.
    expect(screen.queryByText(/Unknown Manufacturer/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Stern/)).not.toBeInTheDocument();
  });
});
