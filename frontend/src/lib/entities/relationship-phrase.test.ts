import { describe, it, expect } from 'vitest';

import {
  edgeFilterLabel,
  inboundRelationshipHeading,
  relationshipLead,
} from './relationship-phrase';

describe('relationship-phrase: re-theme copy', () => {
  it('renders the license axis as official/unofficial in the lead', () => {
    // Display-only: the stored value stays licensed/unlicensed; only re-themes
    // read as official/unofficial (recovering the old tag vocabulary).
    expect(relationshipLead('retheme', 'unknown')).toBe('Re-theme of');
    expect(relationshipLead('retheme', 'licensed')).toBe('Official re-theme of');
    expect(relationshipLead('retheme', 'unlicensed')).toBe('Unofficial re-theme of');
  });

  it('uses official/unofficial in the inbound headings too', () => {
    expect(inboundRelationshipHeading('retheme', 'unknown')).toBe('Re-themes');
    expect(inboundRelationshipHeading('retheme', 'licensed')).toBe('Official Re-themes');
    expect(inboundRelationshipHeading('retheme', 'unlicensed')).toBe('Unofficial Re-themes');
  });
});

describe('edgeFilterLabel', () => {
  it('resolves both directions of a key from the wire value', () => {
    expect(edgeFilterLabel('copy')).toBe('Is a copy');
    expect(edgeFilterLabel('copy:in')).toBe('Has been copied');
    expect(edgeFilterLabel('bootleg')).toBe('Bootleg');
    expect(edgeFilterLabel('bootleg:in')).toBe('Has been bootlegged');
    expect(edgeFilterLabel('conversion:in')).toBe('Has been converted into another game');
    expect(edgeFilterLabel('conversion_kit:in')).toBe('Has been donor for a conversion kit');
    expect(edgeFilterLabel('variant_of')).toBe('Is a variant');
    expect(edgeFilterLabel('variant_of:in')).toBe('Has variants');
  });

  it('falls back to the wire value for a key the map does not know', () => {
    // The backend vocabulary can gain a key before this map learns it; the
    // sidebar must render something deselectable rather than crash.
    expect(edgeFilterLabel('novel_key')).toBe('novel_key');
    expect(edgeFilterLabel('novel_key:in')).toBe('novel_key:in');
  });
});
