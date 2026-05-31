import { describe, it, expect } from 'vitest';
import { reduceTooltip } from './citation-tooltip';
import type { TooltipState } from './citation-tooltip';

// ── reduceTooltip ───────────────────────────────────────���───────

describe('reduceTooltip', () => {
  const initial: TooltipState = { activeId: null, pinned: false };
  const showing = (id: number): TooltipState => ({ activeId: id, pinned: false });
  const pinned = (id: number): TooltipState => ({ activeId: id, pinned: true });

  describe('mouseenter', () => {
    it('shows tooltip for the citation', () => {
      const result = reduceTooltip(initial, { type: 'mouseenter', id: 1 });
      expect(result.activeId).toBe(1);
      expect(result.pinned).toBe(false);
      expect(result.cancelHide).toBe(true);
    });

    it('switches to new citation when not pinned', () => {
      const result = reduceTooltip(showing(1), { type: 'mouseenter', id: 2 });
      expect(result.activeId).toBe(2);
      expect(result.pinned).toBe(false);
    });

    it('does not switch when pinned on a different citation', () => {
      const result = reduceTooltip(pinned(1), { type: 'mouseenter', id: 2 });
      expect(result.activeId).toBe(1);
      expect(result.pinned).toBe(true);
    });
  });

  describe('mouseleave', () => {
    it('schedules hide when not pinned', () => {
      const result = reduceTooltip(showing(1), { type: 'mouseleave', id: 1 });
      expect(result.scheduleHide).toBe(true);
    });

    it('does not schedule hide when pinned', () => {
      const result = reduceTooltip(pinned(1), { type: 'mouseleave', id: 1 });
      expect(result.scheduleHide).toBeUndefined();
    });
  });

  describe('click', () => {
    it('pins the tooltip when not pinned', () => {
      const result = reduceTooltip(showing(1), { type: 'click', id: 1 });
      expect(result.activeId).toBe(1);
      expect(result.pinned).toBe(true);
    });

    it('unpins and hides when clicking the same pinned citation', () => {
      const result = reduceTooltip(pinned(1), { type: 'click', id: 1 });
      expect(result.activeId).toBeNull();
      expect(result.pinned).toBe(false);
    });

    it('switches pin to a different citation', () => {
      const result = reduceTooltip(pinned(1), { type: 'click', id: 2 });
      expect(result.activeId).toBe(2);
      expect(result.pinned).toBe(true);
    });

    it('pins from initial state (mobile tap)', () => {
      const result = reduceTooltip(initial, { type: 'click', id: 1 });
      expect(result.activeId).toBe(1);
      expect(result.pinned).toBe(true);
    });
  });

  describe('focus', () => {
    it('shows tooltip on keyboard focus', () => {
      const result = reduceTooltip(initial, { type: 'focus', id: 1 });
      expect(result.activeId).toBe(1);
      expect(result.pinned).toBe(false);
      expect(result.cancelHide).toBe(true);
    });

    it('does not switch when pinned on a different citation', () => {
      const result = reduceTooltip(pinned(1), { type: 'focus', id: 2 });
      expect(result.activeId).toBe(1);
      expect(result.pinned).toBe(true);
    });
  });

  describe('blur', () => {
    it('schedules hide when not pinned', () => {
      const result = reduceTooltip(showing(1), { type: 'blur', id: 1 });
      expect(result.scheduleHide).toBe(true);
    });

    it('does not schedule hide when pinned', () => {
      const result = reduceTooltip(pinned(1), { type: 'blur', id: 1 });
      expect(result.scheduleHide).toBeUndefined();
    });
  });

  describe('escape', () => {
    it('hides and unpins', () => {
      const result = reduceTooltip(pinned(1), { type: 'escape' });
      expect(result.activeId).toBeNull();
      expect(result.pinned).toBe(false);
    });

    it('hides when showing but not pinned', () => {
      const result = reduceTooltip(showing(1), { type: 'escape' });
      expect(result.activeId).toBeNull();
    });

    it('is a no-op when already hidden', () => {
      const result = reduceTooltip(initial, { type: 'escape' });
      expect(result.activeId).toBeNull();
      expect(result.pinned).toBe(false);
    });
  });

  describe('click-outside', () => {
    it('hides and unpins when pinned', () => {
      const result = reduceTooltip(pinned(1), { type: 'click-outside' });
      expect(result.activeId).toBeNull();
      expect(result.pinned).toBe(false);
    });

    it('is a no-op when not pinned', () => {
      const result = reduceTooltip(showing(1), { type: 'click-outside' });
      expect(result.activeId).toBe(1);
      expect(result.pinned).toBe(false);
    });
  });

  describe('navigate', () => {
    it('dismisses tooltip and signals navigation', () => {
      const result = reduceTooltip(showing(1), { type: 'navigate', id: 1 });
      expect(result.activeId).toBeNull();
      expect(result.pinned).toBe(false);
      expect(result.navigate).toBe(true);
    });

    it('dismisses pinned tooltip', () => {
      const result = reduceTooltip(pinned(1), { type: 'navigate', id: 1 });
      expect(result.activeId).toBeNull();
      expect(result.pinned).toBe(false);
      expect(result.navigate).toBe(true);
    });

    it('works from initial state', () => {
      const result = reduceTooltip(initial, { type: 'navigate', id: 1 });
      expect(result.activeId).toBeNull();
      expect(result.pinned).toBe(false);
      expect(result.navigate).toBe(true);
    });
  });

  describe('tooltip-mouseenter', () => {
    it('cancels pending hide', () => {
      const result = reduceTooltip(showing(1), { type: 'tooltip-mouseenter' });
      expect(result.cancelHide).toBe(true);
      expect(result.activeId).toBe(1);
    });
  });

  describe('tooltip-mouseleave', () => {
    it('schedules hide when not pinned', () => {
      const result = reduceTooltip(showing(1), { type: 'tooltip-mouseleave' });
      expect(result.scheduleHide).toBe(true);
    });

    it('does not schedule hide when pinned', () => {
      const result = reduceTooltip(pinned(1), { type: 'tooltip-mouseleave' });
      expect(result.scheduleHide).toBeUndefined();
    });
  });
});
