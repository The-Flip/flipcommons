import { describe, expect, it } from 'vitest';
import { detectTrigger, formatLinkText, spliceLink } from './wikilink-helpers';

describe('detectTrigger', () => {
  it('detects [[ at cursor position', () => {
    expect(detectTrigger('hello [[', 8)).toBe(6);
  });

  it('detects [[ at the very start of the text', () => {
    expect(detectTrigger('[[', 2)).toBe(0);
  });

  it('returns -1 when no [[ before cursor', () => {
    expect(detectTrigger('hello world', 5)).toBe(-1);
  });

  it('returns -1 when cursor is too early', () => {
    expect(detectTrigger('[', 1)).toBe(-1);
  });

  it('returns -1 for single bracket', () => {
    expect(detectTrigger('hello [x', 7)).toBe(-1);
  });

  it('returns -1 when [[ is not immediately before cursor', () => {
    expect(detectTrigger('hello [[ world', 14)).toBe(-1);
  });

  it('detects [[ after existing link syntax', () => {
    expect(detectTrigger('See [[manufacturer:williams]] and [[', 36)).toBe(34);
  });
});

describe('formatLinkText', () => {
  it('formats a basic link', () => {
    expect(formatLinkText('manufacturer', 'williams')).toBe('[[manufacturer:williams]]');
  });

  it('handles slugs with hyphens', () => {
    expect(formatLinkText('machinemodel', 'medieval-madness')).toBe(
      '[[machinemodel:medieval-madness]]',
    );
  });

  it('formats a citation link with numeric ID', () => {
    expect(formatLinkText('cite', '42')).toBe('[[cite:42]]');
  });
});

describe('spliceLink', () => {
  it('replaces [[ with the link text', () => {
    const result = spliceLink('hello [[', 6, 8, '[[manufacturer:williams]]');
    expect(result.newText).toBe('hello [[manufacturer:williams]]');
    expect(result.newCursorPos).toBe(31);
  });

  it('replaces [[ plus extra typed chars', () => {
    // User typed [[ then "ma" before selecting — cursor is past [[
    const result = spliceLink('hello [[ma', 6, 10, '[[manufacturer:williams]]');
    expect(result.newText).toBe('hello [[manufacturer:williams]]');
    expect(result.newCursorPos).toBe(31);
  });

  it('works at the start of the text', () => {
    const result = spliceLink('[[', 0, 2, '[[title:medieval-madness]]');
    expect(result.newText).toBe('[[title:medieval-madness]]');
    expect(result.newCursorPos).toBe(26);
  });

  it('preserves text after cursor', () => {
    const result = spliceLink('See [[ for details.', 4, 6, '[[title:funhouse]]');
    expect(result.newText).toBe('See [[title:funhouse]] for details.');
    expect(result.newCursorPos).toBe(22);
  });

  it('works in the middle of existing content with links', () => {
    const text = 'First [[manufacturer:williams]] and [[';
    const result = spliceLink(text, 36, 38, '[[title:funhouse]]');
    expect(result.newText).toBe('First [[manufacturer:williams]] and [[title:funhouse]]');
    expect(result.newCursorPos).toBe(54);
  });
});
