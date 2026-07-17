import { describe, it, expect } from 'vitest';

import { inboundRelationshipHeading, relationshipLead } from './relationship-phrase';

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
