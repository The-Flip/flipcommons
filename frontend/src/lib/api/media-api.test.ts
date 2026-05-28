import { describe, expect, it } from 'vitest';

import { MEDIA_CATEGORIES } from '../models/model-meta';
import { MAX_FILE_SIZE_BYTES, IMAGE_ACCEPT } from './media-api';

describe('media-api constants', () => {
  it('MEDIA_CATEGORIES.model has expected values', () => {
    expect(MEDIA_CATEGORIES.model).toEqual(['backglass', 'playfield', 'cabinet', 'other']);
  });

  it('MAX_FILE_SIZE_BYTES is 20 MB', () => {
    expect(MAX_FILE_SIZE_BYTES).toBe(20 * 1024 * 1024);
  });

  it('IMAGE_ACCEPT includes image wildcard and quirk extensions', () => {
    expect(IMAGE_ACCEPT).toContain('image/*');
    expect(IMAGE_ACCEPT).toContain('.heic');
    expect(IMAGE_ACCEPT).toContain('.heif');
    expect(IMAGE_ACCEPT).toContain('.avif');
  });
});
