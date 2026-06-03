import { describe, expect, it } from 'vitest';

import {
  defaultManufacturerSectionSegment,
  findManufacturerSectionBySegment,
  MANUFACTURER_EDIT_SECTIONS,
} from './manufacturer-edit-sections';

describe('manufacturer edit sections', () => {
  it('uses the requested section ordering', () => {
    expect(MANUFACTURER_EDIT_SECTIONS.map((section) => section.key)).toEqual([
      'name',
      'description',
      'basics',
    ]);
  });

  it('defaults to the name section', () => {
    expect(defaultManufacturerSectionSegment()).toBe('name');
  });

  it('looks up sections by segment', () => {
    expect(findManufacturerSectionBySegment('description')?.key).toBe('description');
    expect(findManufacturerSectionBySegment('missing')).toBeUndefined();
  });

  it('does not show the mixed-edit warning for the name section', () => {
    expect(findManufacturerSectionBySegment('name')?.showMixedEditWarning).toBe(false);
  });
});
