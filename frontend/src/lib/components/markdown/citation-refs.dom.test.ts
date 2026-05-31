import { describe, it, expect } from 'vitest';
import { findRefEntry, findFirstInlineMarker } from './citation-refs';

// ── findRefEntry ──────────────────────────────────────────

describe('findRefEntry', () => {
  it('finds element by data-ref-index', () => {
    const container = document.createElement('div');
    const li = document.createElement('li');
    li.setAttribute('data-ref-index', '2');
    container.appendChild(li);

    expect(findRefEntry(container, 2)).toBe(li);
  });

  it('returns null when not found', () => {
    const container = document.createElement('div');
    expect(findRefEntry(container, 99)).toBeNull();
  });
});

// ── findFirstInlineMarker ─────────────────────────────────

describe('findFirstInlineMarker', () => {
  it('finds first sup with matching data-cite-index', () => {
    const container = document.createElement('div');
    const sup1 = document.createElement('sup');
    sup1.setAttribute('data-cite-index', '1');
    const sup2 = document.createElement('sup');
    sup2.setAttribute('data-cite-index', '1');
    container.append(sup1, sup2);

    expect(findFirstInlineMarker(container, 1)).toBe(sup1);
  });

  it('returns null when not found', () => {
    const container = document.createElement('div');
    expect(findFirstInlineMarker(container, 5)).toBeNull();
  });
});
